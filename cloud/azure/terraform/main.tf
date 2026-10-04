# Seedy runners on Azure: a scale set of spot VMs that sits at zero instances. A workflow job
# (.github/workflows/azure-runners.yml) signs in with OIDC and scales it up to the jobs waiting for these
# runners, or you scale it by hand; each VM runs its jobs and deletes itself. Idle cost: the registry.

data "azurerm_client_config" "current" {}

locals {
  suffix              = substr(sha1("${var.subscription_id}/${var.resource_group_name}"), 0, 6)
  repo_scoped         = strcontains(var.github_scope, "/")
  scaler_repositories = var.scaler_repositories != null ? var.scaler_repositories : (local.repo_scoped ? [var.github_scope] : [])
}

resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}

# ---- network: no inbound access; each VM gets its own outbound public IP ----
# (per-VM IPs cost nothing while the scale set is empty, unlike a NAT gateway, and spread Docker Hub's
# per-IP pull limit when VMs pull the Quartus image themselves)

resource "azurerm_virtual_network" "this" {
  name                = "${var.name}-vnet"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  address_space       = [var.address_space]
  tags                = var.tags
}

resource "azurerm_subnet" "runners" {
  name                            = "runners"
  resource_group_name             = azurerm_resource_group.this.name
  virtual_network_name            = azurerm_virtual_network.this.name
  address_prefixes                = [var.address_space]
  default_outbound_access_enabled = false
}

resource "azurerm_network_security_group" "runners" {
  # Azure's default rules: nothing inbound from the internet, all outbound allowed
  name                = "${var.name}-runners-nsg"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = var.tags
}

# ---- identities ----

resource "azurerm_user_assigned_identity" "runner" {
  # on every VM: reads the GitHub credential from Key Vault and deletes its own VM
  name                = "${var.name}-runner"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = var.tags
}

resource "azurerm_user_assigned_identity" "scaler" {
  # used by the GitHub workflow through OIDC (no stored secret): scales the VM scale set up
  name                = "${var.name}-scaler"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = var.tags

  lifecycle {
    precondition {
      condition     = length(local.scaler_repositories) > 0
      error_message = "With an organization github_scope, list the repositories that may scale the runners in scaler_repositories."
    }
  }
}

resource "azurerm_federated_identity_credential" "scaler" {
  for_each                  = toset(local.scaler_repositories)
  name                      = "github-${replace(each.value, "/[^A-Za-z0-9-]/", "-")}"
  user_assigned_identity_id = azurerm_user_assigned_identity.scaler.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:${each.value}:environment:${var.scaler_environment}"
}

# ---- Key Vault: the GitHub credential (set it yourself, so it never enters the Terraform state) ----

resource "azurerm_key_vault" "this" {
  name                       = "${var.name}-kv-${local.suffix}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  tags                       = var.tags
}

resource "azurerm_role_assignment" "deployer_secrets" {
  # lets whoever runs Terraform store the GitHub credential
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "runner_secrets" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.runner.principal_id
  principal_type       = "ServicePrincipal"
}

# ---- least-privilege roles over this resource group ----

resource "azurerm_role_definition" "scaler" {
  name        = "Seedy runner scaler (${local.suffix})"
  scope       = azurerm_resource_group.this.id
  description = "Scale the Seedy runner scale set out, and remove instances that failed to provision."
  permissions {
    actions = [
      "Microsoft.Compute/virtualMachineScaleSets/read",
      "Microsoft.Compute/virtualMachineScaleSets/write",
      "Microsoft.Compute/virtualMachineScaleSets/delete/action",
      "Microsoft.Compute/virtualMachines/read",
      "Microsoft.Compute/virtualMachines/write",
      "Microsoft.Compute/virtualMachines/delete",
      "Microsoft.Compute/disks/read",
      "Microsoft.Compute/disks/write",
      # a custom_image_id from a gallery in this resource group
      "Microsoft.Compute/galleries/read",
      "Microsoft.Compute/galleries/images/read",
      "Microsoft.Compute/galleries/images/versions/read",
      # creating a VM checks that its creator may use the subnet, NSG, public IP and identity
      "Microsoft.Network/virtualNetworks/read",
      "Microsoft.Network/virtualNetworks/subnets/read",
      "Microsoft.Network/virtualNetworks/subnets/join/action",
      "Microsoft.Network/networkInterfaces/read",
      "Microsoft.Network/networkInterfaces/write",
      "Microsoft.Network/networkInterfaces/join/action",
      "Microsoft.Network/networkSecurityGroups/read",
      "Microsoft.Network/networkSecurityGroups/join/action",
      "Microsoft.Network/publicIPAddresses/read",
      "Microsoft.Network/publicIPAddresses/write",
      "Microsoft.Network/publicIPAddresses/join/action",
      "Microsoft.ManagedIdentity/userAssignedIdentities/read",
      "Microsoft.ManagedIdentity/userAssignedIdentities/assign/action",
    ]
  }
  assignable_scopes = [azurerm_resource_group.this.id]
}

resource "azurerm_role_definition" "self_delete" {
  name        = "Seedy runner self-delete (${local.suffix})"
  scope       = azurerm_resource_group.this.id
  description = "Lets a Seedy runner VM delete itself when its work is done."
  permissions {
    actions = [
      "Microsoft.Compute/virtualMachineScaleSets/read",
      "Microsoft.Compute/virtualMachineScaleSets/delete/action",
      "Microsoft.Compute/virtualMachines/read",
      "Microsoft.Compute/virtualMachines/delete",
      "Microsoft.Compute/disks/delete",
      "Microsoft.Network/networkInterfaces/delete",
      "Microsoft.Network/publicIPAddresses/delete",
    ]
  }
  assignable_scopes = [azurerm_resource_group.this.id]
}

resource "azurerm_role_assignment" "scaler" {
  scope              = azurerm_resource_group.this.id
  role_definition_id = azurerm_role_definition.scaler.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.scaler.principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "runner_self_delete" {
  scope              = azurerm_resource_group.this.id
  role_definition_id = azurerm_role_definition.self_delete.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.runner.principal_id
  principal_type     = "ServicePrincipal"
}

# ---- container registry: a local copy of the Quartus image(s) ----
# VMs pull from here, in-region and through their managed identity, never from Docker Hub with its
# per-IP limits. Fill it with `az acr import` (README). Basic costs about $5 a month.

resource "azurerm_container_registry" "this" {
  count                  = var.registry ? 1 : 0
  name                   = "${replace(var.name, "-", "")}${local.suffix}"
  resource_group_name    = azurerm_resource_group.this.name
  location               = azurerm_resource_group.this.location
  sku                    = var.registry_sku
  admin_enabled          = false
  anonymous_pull_enabled = false
  tags                   = var.tags
}

resource "azurerm_role_assignment" "runner_acr_pull" {
  count                = var.registry ? 1 : 0
  scope                = azurerm_container_registry.this[0].id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.runner.principal_id
  principal_type       = "ServicePrincipal"
}

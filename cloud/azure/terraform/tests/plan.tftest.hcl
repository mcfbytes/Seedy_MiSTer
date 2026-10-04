# Offline plan checks with mocked providers: terraform init -backend=false && terraform test

mock_provider "azurerm" {
  # computed values the cloud-init and IDs depend on, known already at plan
  override_during = plan

  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-seedy-runners/providers/Microsoft.ManagedIdentity/userAssignedIdentities/seedy-runner"
      client_id    = "00000000-0000-0000-0000-0000000000c1"
      principal_id = "00000000-0000-0000-0000-0000000000p1"
    }
  }
  mock_resource "azurerm_shared_image" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-seedy-runners/providers/Microsoft.Compute/galleries/seedy_gallery_abc123/images/seedy-runner"
    }
  }
  mock_resource "azurerm_role_definition" {
    defaults = {
      role_definition_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Authorization/roleDefinitions/00000000-0000-0000-0000-0000000000r1"
    }
  }

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id = "00000000-0000-0000-0000-00000000000a"
      object_id = "00000000-0000-0000-0000-00000000000b"
    }
  }
}

mock_provider "tls" {}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  github_scope    = "someone/Core_MiSTer"
}

run "defaults" {
  command = plan

  assert {
    condition     = azurerm_orchestrated_virtual_machine_scale_set.runners.priority == "Spot" && azurerm_orchestrated_virtual_machine_scale_set.runners.eviction_policy == "Delete"
    error_message = "spot VMs, deleted on eviction"
  }
  assert {
    condition     = azurerm_orchestrated_virtual_machine_scale_set.runners.instances == 0
    error_message = "the scale set starts empty"
  }
  assert {
    condition     = azurerm_orchestrated_virtual_machine_scale_set.runners.sku_name == "Standard_D8ads_v5" && length(azurerm_orchestrated_virtual_machine_scale_set.runners.sku_profile) == 0
    error_message = "one size, no instance mix"
  }
  assert {
    condition     = length(azurerm_orchestrated_virtual_machine_scale_set.runners.source_image_reference) == 1 && azurerm_orchestrated_virtual_machine_scale_set.runners.source_image_id == null
    error_message = "stock Ubuntu until a gallery image is chosen"
  }
  assert {
    condition     = azurerm_orchestrated_virtual_machine_scale_set.runners.tags["seedy-max-instances"] == "30"
    error_message = "the scaler's ceiling is tagged on the scale set"
  }
  assert {
    condition = alltrue([for s in [
      "GITHUB_SCOPE='someone/Core_MiSTer'", "GITHUB_APP_ID=''", "RUNNER_LABELS='seedy-azure'", "MAX_JOBS='1'",
      "OnBootSec=720min", "RUNNER_VERSION='latest' /opt/seedy-runner/provision.sh",
    ] : strcontains(base64decode(azurerm_orchestrated_virtual_machine_scale_set.runners.os_profile[0].custom_data), s)])
    error_message = "cloud-init carries the runner configuration"
  }
  assert {
    condition     = azurerm_federated_identity_credential.scaler["someone/Core_MiSTer"].subject == "repo:someone/Core_MiSTer:environment:seedy-azure"
    error_message = "Azure trusts the repository's seedy-azure environment"
  }
  assert {
    condition     = length(tls_private_key.admin) == 1
    error_message = "an SSH key is generated when none is given"
  }
}

run "gallery_image_instance_mix_app" {
  command = plan

  variables {
    use_gallery_image    = true
    vm_sizes             = ["Standard_D8ads_v5", "Standard_D8ads_v6"]
    github_app_id        = "12345"
    spot                 = false
    runner_labels        = ["quartus", "big"]
    admin_ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB7qXv5h3m0xLr8b4jvNMEm6lJ1H9uUw6s0rB2c0yq4P test"
  }

  assert {
    condition     = azurerm_orchestrated_virtual_machine_scale_set.runners.sku_name == "Mix" && length(azurerm_orchestrated_virtual_machine_scale_set.runners.sku_profile[0].virtual_machine_size) == 2
    error_message = "several sizes make an instance mix"
  }
  assert {
    condition     = length(azurerm_orchestrated_virtual_machine_scale_set.runners.source_image_reference) == 0 && endswith(azurerm_orchestrated_virtual_machine_scale_set.runners.source_image_id, "/images/seedy-runner")
    error_message = "the gallery image replaces stock Ubuntu"
  }
  assert {
    condition     = azurerm_orchestrated_virtual_machine_scale_set.runners.priority == "Regular" && azurerm_orchestrated_virtual_machine_scale_set.runners.eviction_policy == null
    error_message = "regular VMs on request"
  }
  assert {
    condition = alltrue([for s in ["GITHUB_APP_ID='12345'", "RUNNER_LABELS='quartus,big'"] :
    strcontains(base64decode(azurerm_orchestrated_virtual_machine_scale_set.runners.os_profile[0].custom_data), s)])
    error_message = "cloud-init carries the app ID and labels"
  }
  assert {
    condition     = length(tls_private_key.admin) == 0
    error_message = "no generated key when one is given"
  }
}

run "organization_needs_scaler_repositories" {
  command = plan

  variables {
    github_scope = "some-org"
  }

  expect_failures = [azurerm_user_assigned_identity.scaler]
}

run "organization_with_repositories" {
  command = plan

  variables {
    github_scope        = "some-org"
    scaler_repositories = ["some-org/A_MiSTer", "some-org/B_MiSTer"]
  }

  assert {
    condition     = length(azurerm_federated_identity_credential.scaler) == 2
    error_message = "one trusted subject per repository"
  }
}

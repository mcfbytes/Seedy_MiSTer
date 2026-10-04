output "vmss_id" {
  description = "Scale set resource ID: the workflow's vmss_id (GitHub variable SEEDY_AZURE_VMSS_ID)."
  value       = azurerm_orchestrated_virtual_machine_scale_set.runners.id
}

output "scaler_client_id" {
  description = "Client ID of the scaler identity: the workflow's client_id (GitHub variable SEEDY_AZURE_CLIENT_ID)."
  value       = azurerm_user_assigned_identity.scaler.client_id
}

output "tenant_id" {
  description = "Entra tenant: the workflow's tenant_id (GitHub variable SEEDY_AZURE_TENANT_ID)."
  value       = data.azurerm_client_config.current.tenant_id
}

output "key_vault_name" {
  description = "Key Vault that holds the GitHub credential (github-pat, or github-app-private-key)."
  value       = azurerm_key_vault.this.name
}

output "runs_on" {
  description = "runs-on value for jobs that should use these runners."
  value       = jsonencode(concat(["self-hosted"], var.runner_labels))
}

output "registry_name" {
  description = "Container registry for the Quartus image(s): az acr import --name <this> ..."
  value       = var.registry ? azurerm_container_registry.this[0].name : null
}

output "registry_login_server" {
  description = "The registry's login server; VMs hand it to jobs as SEEDY_IMAGE_MIRROR."
  value       = var.registry ? azurerm_container_registry.this[0].login_server : null
}

output "admin_ssh_private_key" {
  description = "Generated SSH key of the VMs' admin user (only when admin_ssh_public_key is unset)."
  value       = try(tls_private_key.admin[0].private_key_openssh, null)
  sensitive   = true
}

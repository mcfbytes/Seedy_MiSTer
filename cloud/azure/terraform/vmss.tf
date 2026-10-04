locals {
  image_id = coalesce(var.custom_image_id, "none")

  cloud_init = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    github_scope               = var.github_scope
    github_app_id              = var.github_app_id == null ? "" : var.github_app_id
    github_app_installation_id = var.github_app_installation_id == null ? "" : var.github_app_installation_id
    runner_labels              = join(",", var.runner_labels)
    runner_group_id            = var.runner_group_id
    key_vault_name             = azurerm_key_vault.this.name
    registry                   = var.registry ? azurerm_container_registry.this[0].login_server : ""
    identity_client_id         = azurerm_user_assigned_identity.runner.client_id
    idle_minutes               = var.idle_minutes
    max_jobs                   = var.max_jobs_per_vm
    max_lifetime_minutes       = var.max_lifetime_minutes
    runner_version             = var.runner_version
    provision_sh               = filebase64("${path.module}/../vm/provision.sh")
    agent_sh                   = filebase64("${path.module}/../vm/seedy-runner-agent.sh")
    runner_service             = filebase64("${path.module}/../vm/seedy-runner.service")
    watchdog_service           = filebase64("${path.module}/../vm/seedy-runner-watchdog.service")
  })
}

resource "tls_private_key" "admin" {
  count     = var.admin_ssh_public_key == null ? 1 : 0
  algorithm = "ED25519"
}

resource "azurerm_orchestrated_virtual_machine_scale_set" "runners" {
  name                        = "${var.name}-runners"
  resource_group_name         = azurerm_resource_group.this.name
  location                    = azurerm_resource_group.this.location
  platform_fault_domain_count = 1
  instances                   = 0 # the scaler sets this; Terraform leaves it alone afterwards

  sku_name = length(var.vm_sizes) == 1 ? var.vm_sizes[0] : "Mix"
  dynamic "sku_profile" {
    for_each = length(var.vm_sizes) > 1 ? [1] : []
    content {
      allocation_strategy = var.instance_mix_strategy
      dynamic "virtual_machine_size" {
        for_each = var.vm_sizes
        content {
          name = virtual_machine_size.value
        }
      }
    }
  }

  priority        = var.spot ? "Spot" : "Regular"
  eviction_policy = var.spot ? "Delete" : null
  max_bid_price   = var.spot ? var.spot_max_price : null

  source_image_id = local.image_id == "none" ? null : local.image_id
  dynamic "source_image_reference" {
    for_each = local.image_id == "none" ? [1] : []
    content {
      publisher = "Canonical"
      offer     = "ubuntu-24_04-lts"
      sku       = "server"
      version   = "latest"
    }
  }

  os_profile {
    custom_data = base64encode(local.cloud_init)
    linux_configuration {
      admin_username                  = "seedy"
      computer_name_prefix            = "${var.name}-"
      disable_password_authentication = true
      admin_ssh_key {
        username   = "seedy"
        public_key = var.admin_ssh_public_key != null ? var.admin_ssh_public_key : tls_private_key.admin[0].public_key_openssh
      }
    }
  }

  os_disk {
    storage_account_type = var.ephemeral_os_disk ? "Standard_LRS" : "StandardSSD_LRS"
    caching              = var.ephemeral_os_disk ? "ReadOnly" : "ReadWrite"
    disk_size_gb         = var.os_disk_size_gb
    dynamic "diff_disk_settings" {
      for_each = var.ephemeral_os_disk ? [1] : []
      content {
        option    = "Local"
        placement = "ResourceDisk"
      }
    }
  }

  network_interface {
    name                           = "nic"
    primary                        = true
    network_security_group_id      = azurerm_network_security_group.runners.id
    accelerated_networking_enabled = true
    ip_configuration {
      name      = "ip"
      primary   = true
      subnet_id = azurerm_subnet.runners.id
      public_ip_address {
        name = "pip"
      }
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runner.id]
  }

  boot_diagnostics {} # managed storage: the serial log shows the agent's output

  # the scaler reads its ceiling from here
  tags = merge(var.tags, { "seedy-max-instances" = tostring(var.max_instances) })

  lifecycle {
    ignore_changes = [instances]
  }

  depends_on = [
    azurerm_role_assignment.runner_secrets,
    azurerm_role_assignment.runner_self_delete,
    azurerm_role_assignment.runner_acr_pull,
  ]
}

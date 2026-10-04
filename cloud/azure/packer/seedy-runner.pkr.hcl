# Bakes a Seedy runner image: Ubuntu 24.04 + Docker + the GitHub Actions runner + the Quartus image(s), so
# a VM takes its job a minute or two after boot and never pulls Quartus from Docker Hub.
#
#   packer init seedy-runner.pkr.hcl
#   packer build $(terraform -chdir=../terraform output -raw packer_vars) seedy-runner.pkr.hcl
#
# Signs in with the Azure CLI (az login). Each build adds a version to the gallery; the scale set picks up
# the newest one for the VMs it creates next. Rebuild now and then for OS and runner updates.

packer {
  required_plugins {
    azure = {
      source  = "github.com/hashicorp/azure"
      version = ">= 2.6.0"
    }
  }
}

variable "subscription_id" {
  type = string
}

variable "resource_group" {
  type = string
}

variable "gallery_name" {
  type = string
}

variable "image_name" {
  type    = string
  default = "seedy-runner"
}

variable "location" {
  type = string
}

variable "image_version" {
  description = "Gallery version; the default is the build time (UTC) as YYYY.MDD.hmm, so newer builds sort higher."
  type        = string
  default     = ""
}

variable "build_vm_size" {
  type    = string
  default = "Standard_D4ads_v5"
}

variable "os_disk_size_gb" {
  description = "Image disk size. The scale set's os_disk_size_gb must be at least this."
  type        = number
  default     = 64
}

variable "prepull_images" {
  description = "Docker images to bake in, exactly as Seedy names them (tag@digest), so Seedy finds them locally."
  type        = list(string)
  default = [
    # Quartus 17.0.2 Lite, the MiSTer standard; keep in step with the digests in .github/workflows/seedy.yml
    "theypsilon/quartus-lite-c5:17.0.2@sha256:42e6c06da3af486f9cfea74acb5c1af9b63a77d0f16e3bf093215216e209b7ad",
  ]
}

variable "runner_version" {
  type    = string
  default = "latest"
}

locals {
  now = timestamp()
  # "+ 0" drops leading zeros, which gallery versions don't allow: 2026-01-04 00:05 -> 2026.104.5
  image_version = var.image_version != "" ? var.image_version : "${formatdate("YYYY", local.now)}.${formatdate("MDD", local.now) + 0}.${formatdate("hmm", local.now) + 0}"
}

source "azure-arm" "seedy_runner" {
  use_azure_cli_auth = true
  subscription_id    = var.subscription_id

  os_type         = "Linux"
  image_publisher = "Canonical"
  image_offer     = "ubuntu-24_04-lts"
  image_sku       = "server"
  location        = var.location
  vm_size         = var.build_vm_size
  os_disk_size_gb = var.os_disk_size_gb

  shared_image_gallery_destination {
    subscription         = var.subscription_id
    resource_group       = var.resource_group
    gallery_name         = var.gallery_name
    image_name           = var.image_name
    image_version        = local.image_version
    storage_account_type = "Standard_LRS"
    target_region {
      name = var.location
    }
  }

  azure_tags = {
    purpose = "seedy-runner-image-build"
  }
}

build {
  sources = ["source.azure-arm.seedy_runner"]

  provisioner "file" {
    source      = "${path.root}/../vm/provision.sh"
    destination = "/tmp/provision.sh"
  }

  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} sudo -E bash '{{ .Path }}'"
    environment_vars = [
      "PREPULL_IMAGES=${join(" ", var.prepull_images)}",
      "RUNNER_VERSION=${var.runner_version}",
    ]
    inline = [
      "set -e",
      "mkdir -p /opt/seedy-runner",
      "install -m 0755 /tmp/provision.sh /opt/seedy-runner/provision.sh",
      "/opt/seedy-runner/provision.sh",
    ]
  }

  provisioner "shell" {
    # generalize, so each VM gets its own identity and runs cloud-init on first boot
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} sudo -E sh '{{ .Path }}'"
    inline = [
      "cloud-init clean --logs",
      "/usr/sbin/waagent -force -deprovision+user && export HISTSIZE=0 && sync",
    ]
    inline_shebang = "/bin/sh -x"
  }
}

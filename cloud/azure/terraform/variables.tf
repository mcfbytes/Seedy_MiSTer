# ---- where ----

variable "subscription_id" {
  description = "Azure subscription to deploy into."
  type        = string
}

variable "location" {
  description = "Azure region. Spot prices and capacity differ by region; check the Azure pricing page for yours."
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Resource group created for the runners. Keep it dedicated: the runner identities hold rights over it."
  type        = string
  default     = "rg-seedy-runners"
}

variable "name" {
  description = "Prefix for resource names."
  type        = string
  default     = "seedy"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,11}$", var.name))
    error_message = "Use 2-12 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "address_space" {
  description = "Address range of the runners' virtual network (one subnet uses all of it)."
  type        = string
  default     = "10.42.0.0/24"
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
  default     = {}
}

# ---- GitHub ----

variable "github_scope" {
  description = "Where runners register: \"owner/repo\" for one repository, or \"org\" for an organization."
  type        = string
  validation {
    condition     = can(regex("^[A-Za-z0-9-]+(/[A-Za-z0-9._-]+)?$", var.github_scope))
    error_message = "Use \"owner/repo\" or \"org\"."
  }
}

variable "github_app_id" {
  description = "GitHub App ID, when runners register with a GitHub App (key in Key Vault as github-app-private-key). Null: a fine-grained PAT in Key Vault as github-pat."
  type        = string
  default     = null
  validation {
    condition     = var.github_app_id == null || can(regex("^[0-9]+$", var.github_app_id))
    error_message = "A GitHub App ID is a number."
  }
}

variable "github_app_installation_id" {
  description = "Installation ID of the GitHub App. Null: looked up from github_scope."
  type        = string
  default     = null
  validation {
    condition     = var.github_app_installation_id == null || can(regex("^[0-9]+$", var.github_app_installation_id))
    error_message = "An installation ID is a number."
  }
}

variable "runner_labels" {
  description = "Labels of the runners, besides self-hosted, linux and x64. Jobs pick them with runs-on; the scaler counts the jobs that ask for the first one."
  type        = list(string)
  default     = ["seedy-azure"]
  validation {
    condition     = length(var.runner_labels) > 0 && alltrue([for l in var.runner_labels : can(regex("^[A-Za-z0-9._-]+$", l))])
    error_message = "At least one label; letters, digits, '.', '_' and '-' only."
  }
}

variable "runner_group_id" {
  description = "Runner group to register in. 1 is the default group (the only one for a repository)."
  type        = number
  default     = 1
}

variable "scaler_repositories" {
  description = "Repositories (\"owner/repo\") whose workflows may scale the runners up. Null: the repository in github_scope."
  type        = list(string)
  default     = null
}

variable "scaler_environment" {
  description = "GitHub environment the scaling job runs in; its OIDC subject is what Azure trusts. Must match the workflow's environment input."
  type        = string
  default     = "seedy-azure"
}

# ---- machines ----

variable "vm_sizes" {
  description = "VM size, or up to 5 sizes for a scale set instance mix (more spot capacity, less uniform compile times). Sizes need a local temp disk for the ephemeral OS disk (the 'd' in D8ads_v5)."
  type        = list(string)
  default     = ["Standard_D8ads_v5"]
  validation {
    condition     = length(var.vm_sizes) >= 1 && length(var.vm_sizes) <= 5
    error_message = "Give 1 to 5 VM sizes."
  }
}

variable "instance_mix_strategy" {
  description = "With several vm_sizes: LowestPrice or CapacityOptimized."
  type        = string
  default     = "CapacityOptimized"
}

variable "spot" {
  description = "Use Spot VMs (much cheaper; Azure may evict one mid-job)."
  type        = bool
  default     = true
}

variable "spot_max_price" {
  description = "Highest hourly price per VM in USD; -1 pays up to the on-demand price and is never evicted for price."
  type        = number
  default     = -1
}

variable "max_instances" {
  description = "Most VMs the scaler may run at once. Each needs vCPU quota (Spot quota for spot VMs)."
  type        = number
  default     = 30
}

variable "ephemeral_os_disk" {
  description = "OS disk on the VM's local temp disk: faster, free, gone with the VM. Needs a size with a temp disk at least os_disk_size_gb big."
  type        = bool
  default     = true
}

variable "os_disk_size_gb" {
  description = "OS disk size. The Quartus image takes about 10 GB, each running compile 1-2 GB."
  type        = number
  default     = 128
}

variable "custom_image_id" {
  description = "Image to boot instead of stock Ubuntu 24.04 (gallery image definition or version, or managed image). VMs still run provision.sh at boot, unless the image has /opt/seedy-runner/.provisioned (from running provision.sh while building it)."
  type        = string
  default     = null
}

variable "registry" {
  description = "Create a container registry for local copies of the Quartus image(s), so VMs never pull from Docker Hub."
  type        = bool
  default     = true
}

variable "registry_sku" {
  description = "Registry tier: Basic (~$5/month) or Standard (~$20/month, twice the pull throughput for large fan-outs)."
  type        = string
  default     = "Basic"
}

variable "admin_ssh_public_key" {
  description = "SSH public key for the VMs' admin user. No inbound port is open; this matters only if you add one. Null: a generated key (private half in the Terraform state)."
  type        = string
  default     = null
}

# ---- lifecycle ----

variable "runner_version" {
  description = "GitHub Actions runner version for VMs that provision at boot, or \"latest\"."
  type        = string
  default     = "latest"
}

variable "idle_minutes" {
  description = "A VM that waits this long without getting a job deletes itself."
  type        = number
  default     = 10
}

variable "max_jobs_per_vm" {
  description = "Jobs a VM runs before deleting itself. 1 (the default) gives every job a clean machine."
  type        = number
  default     = 1
}

variable "max_lifetime_minutes" {
  description = "Safety net: a VM deletes itself this long after boot, job or not. Keep it above your longest job (Seedy's job_timeout_minutes)."
  type        = number
  default     = 720
}

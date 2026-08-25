variable "project_id" {
  description = "Google Cloud project ID."
  type        = string
}

variable "region" {
  description = "Google Cloud region used by ShopSense resources."
  type        = string
  default     = "asia-south1"
}
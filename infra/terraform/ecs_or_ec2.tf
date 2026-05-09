// Placeholder ECS or EC2 resource
resource "null_resource" "placeholder" {
  triggers = {
    always = timestamp()
  }
}

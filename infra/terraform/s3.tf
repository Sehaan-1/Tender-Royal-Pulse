// Placeholder S3 bucket
resource "aws_s3_bucket" "placeholder" {
  bucket = "tenderpulse-placeholder-bucket"
  acl    = "private"
}

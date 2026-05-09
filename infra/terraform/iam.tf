// Placeholder IAM roles/policies
resource "aws_iam_role" "placeholder" {
  name = "placeholder-role"
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}
EOF
}

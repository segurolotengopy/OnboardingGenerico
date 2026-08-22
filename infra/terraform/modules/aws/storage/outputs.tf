output "documents_bucket_name" {
  description = "Nombre del bucket de imagenes de documentos de identidad."
  value       = aws_s3_bucket.this["documents"].bucket
}

output "documents_bucket_arn" {
  description = "ARN del bucket de documentos. Se pasa al modulo de identidad para el scoping por prefijo de tenant."
  value       = aws_s3_bucket.this["documents"].arn
}

output "biometrics_bucket_name" {
  description = "Nombre del bucket de datos biometricos."
  value       = aws_s3_bucket.this["biometrics"].bucket
}

output "biometrics_bucket_arn" {
  description = "ARN del bucket de datos biometricos."
  value       = aws_s3_bucket.this["biometrics"].arn
}

output "staging_bucket_name" {
  description = "Nombre del bucket de artefactos intermedios efimeros."
  value       = aws_s3_bucket.this["staging"].bucket
}

output "staging_bucket_arn" {
  description = "ARN del bucket de artefactos intermedios."
  value       = aws_s3_bucket.this["staging"].arn
}

output "evidence_bucket_name" {
  description = "Nombre del bucket WORM de evidencia de auditoria."
  value       = aws_s3_bucket.evidence.bucket
}

output "evidence_bucket_arn" {
  description = "ARN del bucket WORM de evidencia de auditoria."
  value       = aws_s3_bucket.evidence.arn
}

output "tenant_scoped_bucket_arns" {
  description = "ARNs de los buckets sujetos a scoping por prefijo de tenant. Es el valor que espera tenant_bucket_arns del modulo de identidad."
  value = [
    aws_s3_bucket.this["documents"].arn,
    aws_s3_bucket.this["biometrics"].arn,
    aws_s3_bucket.this["staging"].arn,
  ]
}

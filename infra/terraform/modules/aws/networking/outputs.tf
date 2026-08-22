output "vpc_id" {
  description = "Identificador de la VPC del middleware."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "Bloque CIDR de la VPC, util para reglas de politica de recursos."
  value       = aws_vpc.this.cidr_block
}

output "private_subnet_ids" {
  description = "Lista de identificadores de las subredes privadas, en el orden de las zonas de disponibilidad configuradas."
  value       = [for s in aws_subnet.private : s.id]
}

output "compute_security_group_id" {
  description = "Grupo de seguridad que deben usar las ENIs de Lambda y demas computo dentro de la VPC."
  value       = aws_security_group.compute.id
}

output "s3_gateway_endpoint_id" {
  description = "Identificador del VPC endpoint de S3, necesario para condicionar politicas de bucket con aws:sourceVpce."
  value       = aws_vpc_endpoint.s3.id
}

output "dynamodb_gateway_endpoint_id" {
  description = "Identificador del VPC endpoint de DynamoDB."
  value       = aws_vpc_endpoint.dynamodb.id
}

output "interface_endpoint_ids" {
  description = "Mapa de nombre logico de servicio a identificador del VPC endpoint de tipo Interface."
  value       = { for k, v in aws_vpc_endpoint.interface : k => v.id }
}

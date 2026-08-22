output "function_arns" {
  description = "Mapa de nombre logico a ARN de la funcion, tanto zip como contenedor."
  value = merge(
    { for k, v in aws_lambda_function.zip : k => v.arn },
    { for k, v in aws_lambda_function.container : k => v.arn },
  )
}

output "function_names" {
  description = "Mapa de nombre logico a nombre completo de la funcion."
  value = merge(
    { for k, v in aws_lambda_function.zip : k => v.function_name },
    { for k, v in aws_lambda_function.container : k => v.function_name },
  )
}

output "function_invoke_arns" {
  description = "Mapa de nombre logico a invoke ARN. Es el valor que espera la integracion AWS_PROXY de API Gateway."
  value = merge(
    { for k, v in aws_lambda_function.zip : k => v.invoke_arn },
    { for k, v in aws_lambda_function.container : k => v.invoke_arn },
  )
}

output "execution_role_arn" {
  description = "ARN del rol de ejecucion compartido de las funciones."
  value       = aws_iam_role.execution.arn
}

output "execution_role_name" {
  description = "Nombre del rol de ejecucion, util para adjuntar politicas adicionales desde otros modulos."
  value       = aws_iam_role.execution.name
}

output "ecr_repository_urls" {
  description = "Mapa de nombre logico a URL del repositorio de ECR. Es el destino del push del pipeline de construccion."
  value       = { for k, v in aws_ecr_repository.this : k => v.repository_url }
}

output "shared_layer_arn" {
  description = "ARN de la version de la capa compartida, o nulo si no se creo."
  value       = try(aws_lambda_layer_version.shared[0].arn, null)
}

output "log_group_names" {
  description = "Mapa de nombre logico a nombre del log group de la funcion."
  value       = { for k, v in aws_cloudwatch_log_group.functions : k => v.name }
}

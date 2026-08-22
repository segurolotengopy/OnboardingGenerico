output "parent_state_machine_arn" {
  description = "ARN de la maquina de estado Standard que orquesta la saga de onboarding."
  value       = aws_sfn_state_machine.parent.arn
}

output "parent_state_machine_name" {
  description = "Nombre de la maquina de estado padre."
  value       = aws_sfn_state_machine.parent.name
}

output "ocr_express_state_machine_arn" {
  description = "ARN de la maquina de estado Express de extraccion documental."
  value       = aws_sfn_state_machine.ocr_express.arn
}

output "biometrics_express_state_machine_arn" {
  description = "ARN de la maquina de estado Express de biometria."
  value       = aws_sfn_state_machine.biometrics_express.arn
}

output "apigw_start_execution_role_arn" {
  description = "ARN del rol que asume API Gateway para llamar a StartExecution sin Lambda intermedia."
  value       = aws_iam_role.apigw_start_execution.arn
}

output "start_execution_request_template" {
  description = "Plantilla VTL de la integracion directa API Gateway a StartExecution. El tenant se toma del contexto del autorizador, nunca del cuerpo de la peticion."
  value       = local.start_execution_request_template
}

output "log_group_names" {
  description = "Nombres de los log groups de las tres maquinas de estado."
  value = {
    parent     = aws_cloudwatch_log_group.parent.name
    ocr        = aws_cloudwatch_log_group.ocr_express.name
    biometrics = aws_cloudwatch_log_group.biometrics_express.name
  }
}

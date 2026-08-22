# Modulo `aws/networking`

## Que crea

- Una VPC con DNS y nombres DNS habilitados (requisito de los endpoints de tipo Interface).
- Subredes **privadas** (una por zona de disponibilidad) y su tabla de rutas. No hay subredes publicas por defecto.
- VPC endpoints de tipo **Gateway** para S3 y DynamoDB (sin coste por hora).
- VPC endpoints de tipo **Interface** para KMS, Secrets Manager, ECR (`api` y `dkr`), CloudWatch Logs, Step Functions y STS.
- Grupos de seguridad para el computo (`sg-compute`, solo egreso 443) y para los endpoints (`sg-vpce`, ingreso 443 solo desde el computo).
- Opcionalmente Internet Gateway + NAT Gateway, apagados por defecto.

## Como se usa

```hcl
module "networking" {
  source     = "../../modules/aws/networking"
  env        = var.env
  aws_region = var.aws_region

  private_subnets = {
    "us-east-1a" = "10.60.1.0/24"
    "us-east-1b" = "10.60.2.0/24"
  }

  enable_interface_endpoints = true
  enable_nat_gateway         = false
}
```

Las funciones Lambda que deban correr dentro de la VPC reciben
`module.networking.private_subnet_ids` y `module.networking.compute_security_group_id`.

## Advertencias

- **El egreso a Internet es opt-in.** Sin `enable_nat_gateway = true`, una Lambda dentro de la VPC no
  puede llamar a un proveedor SaaS externo (liveness, buro de credito). Es intencional: obliga a
  declarar el egreso, pero produce timeouts silenciosos si se olvida.
- **Los endpoints de tipo Interface cuestan por hora y por ENI**, y se multiplican por zona de
  disponibilidad. Siete servicios en dos zonas son catorce ENIs facturadas de forma continua. En `dev`
  conviene poner `enable_interface_endpoints = false` y aceptar la salida por NAT o el uso fuera de VPC.
- **Meter una Lambda en la VPC solo es necesario si accede a recursos privados.** DynamoDB, S3 y KMS
  son alcanzables desde fuera de la VPC; poner la funcion dentro de la VPC sin necesidad agrega ENIs,
  complejidad y limites de direcciones IP sin beneficio de seguridad real.
- `private_dns_enabled = true` en los endpoints de tipo Interface hace que el nombre publico del
  servicio resuelva a la IP privada. Si se despliega en una VPC con reglas de DNS heredadas de una
  Transit Gateway, verifique que no haya conflicto de resolucion.
- La subred de NAT se crea **sin** `map_public_ip_on_launch`; la IP publica la aporta la EIP asociada al
  NAT Gateway, no las instancias.
- Dimensione los CIDR con holgura: cada ENI de Lambda consume una direccion IP de la subred y las ENIs
  no se liberan de inmediato al reducirse la concurrencia.

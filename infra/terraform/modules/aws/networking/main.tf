# ---------------------------------------------------------------------------
# Red privada para el middleware de onboarding.
#
# Diseño: no hay subredes publicas ni Internet Gateway. Todo el computo
# serverless corre en subredes privadas y alcanza los servicios de AWS a traves
# de VPC endpoints. Si un adaptador necesita salir a Internet (proveedor SaaS de
# liveness, buro de credito) se agrega un NAT Gateway de forma explicita con
# `var.enable_nat_gateway`, para que el egreso a Internet sea una decision
# consciente y auditable, nunca el valor por defecto.
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"

  # Endpoints de tipo Interface (PrivateLink). Cada uno crea ENIs en las
  # subredes privadas y cuesta por hora, por eso son parametrizables.
  interface_endpoints = var.enable_interface_endpoints ? {
    kms            = "com.amazonaws.${var.aws_region}.kms"
    secretsmanager = "com.amazonaws.${var.aws_region}.secretsmanager"
    ecr_api        = "com.amazonaws.${var.aws_region}.ecr.api"
    ecr_dkr        = "com.amazonaws.${var.aws_region}.ecr.dkr"
    logs           = "com.amazonaws.${var.aws_region}.logs"
    states         = "com.amazonaws.${var.aws_region}.states"
    sts            = "com.amazonaws.${var.aws_region}.sts"
  } : {}
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # requisito de los endpoints de tipo Interface

  tags = merge(var.tags, { Name = "${local.name}-vpc" })
}

# Subredes privadas, una por zona de disponibilidad.
resource "aws_subnet" "private" {
  for_each = var.private_subnets

  vpc_id            = aws_vpc.this.id
  cidr_block        = each.value
  availability_zone = each.key

  # Nunca se asigna IP publica: estas subredes no tienen ruta a Internet salvo
  # via NAT explicito.
  map_public_ip_on_launch = false

  tags = merge(var.tags, { Name = "${local.name}-private-${each.key}" })
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${local.name}-rt-private" })
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

# ---------------------------------------------------------------------------
# Salida a Internet opcional (proveedores SaaS externos)
# ---------------------------------------------------------------------------

resource "aws_subnet" "nat" {
  count = var.enable_nat_gateway ? 1 : 0

  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.nat_subnet_cidr
  availability_zone       = keys(var.private_subnets)[0]
  map_public_ip_on_launch = false

  tags = merge(var.tags, { Name = "${local.name}-nat-subnet" })
}

resource "aws_internet_gateway" "this" {
  count = var.enable_nat_gateway ? 1 : 0

  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${local.name}-igw" })
}

resource "aws_eip" "nat" {
  count = var.enable_nat_gateway ? 1 : 0

  domain = "vpc"
  tags   = merge(var.tags, { Name = "${local.name}-nat-eip" })
}

resource "aws_nat_gateway" "this" {
  count = var.enable_nat_gateway ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.nat[0].id
  tags          = merge(var.tags, { Name = "${local.name}-nat" })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route" "private_to_nat" {
  count = var.enable_nat_gateway ? 1 : 0

  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[0].id
}

# ---------------------------------------------------------------------------
# Grupos de seguridad
# ---------------------------------------------------------------------------

# SG de las funciones Lambda y de cualquier ENI de computo dentro de la VPC.
resource "aws_security_group" "compute" {
  name        = "${local.name}-sg-compute"
  description = "ENIs de computo serverless: solo egreso HTTPS"
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${local.name}-sg-compute" })
}

resource "aws_vpc_security_group_egress_rule" "compute_https" {
  security_group_id = aws_security_group.compute.id
  description       = "Egreso HTTPS hacia endpoints de servicio y, si aplica, NAT"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

# SG de los VPC endpoints de tipo Interface. Solo acepta 443 desde el computo.
resource "aws_security_group" "vpc_endpoints" {
  name        = "${local.name}-sg-vpce"
  description = "VPC endpoints de tipo Interface"
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${local.name}-sg-vpce" })
}

resource "aws_vpc_security_group_ingress_rule" "vpce_from_compute" {
  security_group_id            = aws_security_group.vpc_endpoints.id
  description                  = "HTTPS desde el computo serverless"
  referenced_security_group_id = aws_security_group.compute.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

# ---------------------------------------------------------------------------
# VPC endpoints
# ---------------------------------------------------------------------------

# Gateway endpoints: sin coste por hora, se asocian a la tabla de rutas.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = merge(var.tags, { Name = "${local.name}-vpce-s3" })
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = merge(var.tags, { Name = "${local.name}-vpce-dynamodb" })
}

resource "aws_vpc_endpoint" "interface" {
  for_each = local.interface_endpoints

  vpc_id              = aws_vpc.this.id
  service_name        = each.value
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [for s in aws_subnet.private : s.id]
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = merge(var.tags, { Name = "${local.name}-vpce-${each.key}" })
}

# Modulo `gcp/identity`

## Que crea

- **Identity Platform** con multi-tenancy habilitada y un tenant por entrada de `var.tenants`.
- **Cuenta de servicio del runtime** y **una cuenta de servicio dedicada por tenant premium**.
- **Workload Identity Federation**: pool, proveedor OIDC con `attribute_mapping` y
  `attribute_condition`, y vinculacion de cada tenant premium a su cuenta de servicio mediante
  `principalSet://.../attribute.tenant/<valor>`.
- **Condiciones de IAM sobre Cloud Storage** con `resource.name.startsWith(...)` por prefijo de tenant.
- **Data Access audit logs** habilitados sobre Firestore, Cloud Storage, Cloud KMS y Secret Manager.
- **VPC Service Controls**: recurso **comentado** con instrucciones (requiere permisos de Organizacion).

## Advertencias

### 🔴 Brecha estructural: no existe `dynamodb:LeadingKeys` en GCP

Esto no es una opinion. Las condiciones de IAM exponen `resource.type`, `resource.name`,
`resource.service`, `resource.matchTag()`, `request.time`, `principal.type` y `principal.subject`.
**Ninguna permite condicionar sobre el prefijo de una clave de fila o el identificador de un
documento**, y Firestore no acepta condiciones a nivel de documento en sus bindings de rol.

Y el complemento del problema: **las Security Rules de Firestore no protegen un backend**. Las
bibliotecas de cliente de servidor las omiten por completo y se autentican con credenciales por
defecto de la aplicacion. Solo protegen SDK de cliente movil o web.

**Consecuencia:** en GCP, si el codigo tiene la cuenta de servicio de Firestore, puede leer todos los
tenants. La barrera es el codigo, no la plataforma. Es una brecha **silenciosa**: el sistema funciona
igual de bien mal aislado que bien aislado.

### Como se compensa en este repositorio

| Capa | Mecanismo | Que consigue | Que no consigue |
|---|---|---|---|
| 1. Criptografica (**primaria**) | Cifrado de sobre por tenant con `tenant_id` como Associated Data (`gcp/kms`) | Un error de alcance produce **fallo de descifrado**, no fuga | No impide el acceso, lo hace inutil |
| 2. Plataforma | Base de datos Firestore por tenant premium (`gcp/data`), IAM sobre el recurso `database` | Aislamiento real en el plano de datos | Tope de **100 bases de datos por proyecto** |
| 3. Perimetro | VPC Service Controls (comentado aqui) | Impide exfiltracion fuera del perimetro | Granularidad de **proyecto**, no de fila |
| 4. Deteccion | Data Access audit logs + alerta de desalineacion tenant/token | Traza de quien leyo que | Detecta, no previene |

Y en el codigo: **un unico repositorio con alcance de tenant** por el que pasa toda consulta, con
pruebas de arquitectura que fallen si el cliente de Firestore se importa fuera del adaptador.

**Direccion de diseno:** escriba el puerto de aislamiento asumiendo el modelo de GCP (aplicacion
explicita) y deje que AWS lo refuerce con `LeadingKeys`. Al reves, el adaptador de GCP queda
estructuralmente inseguro.

### Otras advertencias

- **Identity Platform sin instrumento de facturacion permite solo 2 tenants por proyecto.** Con
  facturacion asociada son ilimitados. Es un tope que se descubre tarde y de golpe.
- **Workload Identity Federation no es un sustituto de los session tags.** Gobierna a que **recursos**
  de GCP accede una identidad, no que **filas** puede leer dentro de una base de datos.
- **La creacion de cuentas esta limitada a 100 por hora y por IP** en Identity Platform, ademas de las
  cuotas de sign-in (45.000/min con token custom, 18.000 intercambios de token/min).
- **Cognito usa `cognito:groups`; Identity Platform usa custom claims.** El puerto debe normalizar a un
  contexto de tenant propio; no exponga ninguno de los dos formatos.
- **Data Access audit logs tienen coste** y en un middleware de alto volumen sobre Firestore no es
  despreciable. Use filtros de exclusion para el ruido, pero **nunca excluya accesos a datos de
  tenant**: son justamente los que hay que poder demostrar.
- **VPC Service Controls debe aplicarse primero en modo dry-run.** Un perimetro mal dimensionado corta
  el trafico legitimo de golpe y sin aviso.
- `display_name` de `google_identity_platform_tenant` esta limitado en longitud; el modulo lo trunca a
  20 caracteres. Con identificadores de tenant largos puede haber colisiones: revise el valor generado.

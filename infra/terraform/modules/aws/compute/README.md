# Modulo `aws/compute`

## Que crea

- **Funciones zip** (`var.zip_functions`) para la logica de negocio: resolucion de plan, scoring,
  despacho de revision, registro de decisiones. Runtime gestionado, `arm64` por defecto.
- **Funciones de contenedor** (`var.container_functions`) para inferencia: preprocesado con OpenCV,
  modelos ONNX de calidad de imagen y embeddings faciales. Cada una con su repositorio de **ECR**
  (tags inmutables, escaneo al hacer push, cifrado con la llave de plataforma) y su politica de ciclo
  de vida.
- **Capa compartida** opcional con el nucleo hexagonal.
- **Rol de ejecucion compartido** de menor privilegio: **no** accede a datos de tenant con su propia
  identidad; solo puede `sts:AssumeRole` + `sts:TagSession` sobre el rol tenant-scoped.
- **Log groups explicitos** con retencion y cifrado controlados.
- **Alias `live` y concurrencia aprovisionada** para las funciones que lo declaren.

## Como se usa

```hcl
module "compute" {
  source = "../../modules/aws/compute"
  env    = var.env

  zip_functions = {
    "plan-resolver" = {
      description = "Resuelve el plan de pasos contra el Registro de Capacidades"
      handler     = "onboarding_generico.adapters.aws.plan_resolver.handler"
      s3_key      = "lambdas/plan-resolver-v1.zip"
      memory_mb   = 512
    }
  }

  container_functions = {
    "face-match" = {
      description  = "Embeddings faciales y similitud coseno con ONNX Runtime"
      image_tag    = "v1.4.0"
      architecture = "x86_64"
      timeout_seconds      = 60
      provisioned_concurrency = 2
    }
  }

  inference_memory_mb = 4096 # punto de partida: perfile antes de fijarlo

  core_table_name         = module.data.core_table_name
  capabilities_table_name = module.data.capabilities_table_name
  capabilities_table_arn  = module.data.capabilities_table_arn
  # ... resto de referencias a data / storage / kms / identity
}
```

## Advertencias

- 🔴 **No fije la memoria por reputacion.** El rango real de Lambda es **128 MB a 10.240 MB** en
  incrementos de 1 MB. La cifra de 3.008 MB fue el maximo historico hasta diciembre de 2020 y lleva
  anios obsoleta. **No existe** ningun requisito de memoria ligado a AVX-512: la documentacion de
  Lambda cubre **AVX2**, y `arm64` usa NEON. `inference_memory_mb` es un punto de partida; el valor
  correcto sale de perfilar la funcion real con su modelo real.
- **La vCPU es proporcional a la memoria.** Subir memoria puede *bajar* el coste total si la latencia
  cae mas de lo que sube el precio por milisegundo. Solo se sabe midiendo.
- **`arm64` no admite AVX2.** Si una dependencia nativa lo requiere, fije `architecture = "x86_64"` en
  esa funcion concreta, no en todas.
- **Imagen de contenedor: 10 GB descomprimida**; paquete zip: 50 MB comprimido y 250 MB descomprimido
  incluyendo capas. Un modelo ONNX mediano ya obliga a contenedor.
- **`/tmp` en Lambda es disco real** (512 MB a 10.240 MB) y **no** descuenta de la memoria. Esto es una
  diferencia importante frente a Cloud Run, donde el sistema de archivos escribible es tmpfs y si
  consume memoria: un adaptador portado tal cual perdera memoria util en GCP.
- **Payload de invocacion: 6 MB sincrono, 1 MB asincrono.** Las imagenes viajan por S3.
- **Concurrencia por defecto: 1.000 por region**, con burst de 1.000 entornos cada 10 segundos por
  funcion. `reserved_concurrency` acota el gasto de una funcion, pero **resta de la cuota compartida
  de la cuenta**: reservar de mas puede dejar sin concurrencia al resto.
- **La concurrencia aprovisionada se factura de forma continua**, atienda o no peticiones, y exige
  alias o version publicada. En `dev` debe ser cero.
- **El limite agregado de variables de entorno es 4 KB.** No use variables de entorno como almacen de
  configuracion: para eso esta el Registro de Capacidades.
- **Tags inmutables en ECR** implican que un redespliegue exige un tag nuevo. Es intencional: da
  reproducibilidad y evita que `v1` cambie de digest bajo los pies.
- Meter una funcion en la VPC solo es necesario si accede a recursos privados. Hacerlo "por seguridad"
  agrega ENIs, consumo de IPs y latencia de arranque sin beneficio real.

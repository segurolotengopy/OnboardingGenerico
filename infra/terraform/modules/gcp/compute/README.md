# Modulo `gcp/compute`

## Que crea

- **Repositorio de Artifact Registry** con tags inmutables, CMEK y politicas de limpieza declarativas.
- **Servicios de Cloud Run v2** (`var.services`) con escalado, concurrencia, recursos, sondas de
  arranque y vivacidad, Direct VPC egress opcional, GPU opcional y secretos montados con **version
  fija**.
- **Jobs de Cloud Run v2** (`var.jobs`) para trabajo por lotes.
- **Bindings `roles/run.invoker`**: ningun servicio es publico.

## Como se usa

```hcl
module "compute" {
  source     = "../../modules/gcp/compute"
  project_id = var.project_id
  env        = var.env
  region     = var.region

  runtime_service_account_email = module.identity.runtime_service_account_email

  services = {
    composer = {
      description   = "Nucleo hexagonal: plan, scoring y decisiones"
      image_name    = "composer"
      cpu           = "1"
      memory        = "2Gi"
      concurrency   = 80
      min_instances = 1
    }

    biometrics = {
      description          = "Face match con ONNX Runtime"
      image_name           = "biometrics"
      cpu                  = "4"
      memory               = "8Gi"
      concurrency          = 2   # ONNX con concurrencia alta satura la CPU
      min_instances        = 1
      always_allocated_cpu = true
      timeout_seconds      = 120
    }
  }

  image_names = ["composer", "biometrics"]
  # ... referencias a data / storage / kms / networking
}
```

## Advertencias

- 🔴 **El sistema de archivos escribible de Cloud Run es tmpfs y consume memoria.** Un adaptador que en
  Lambda escribe imagenes intermedias en `/tmp` asumiendo disco real, aqui le esta quitando memoria al
  modelo. Alternativas: montaje de Cloud Storage FUSE o Filestore. Esta es la trampa mas cara de todo
  el porte.
- 🔴 **La concurrencia por defecto no es 1.** Lambda garantiza una peticion por instancia; Cloud Run
  admite hasta 1.000. **ONNX Runtime con concurrencia alta necesita sesiones seguras entre hilos y
  control de hilos intra-op**, o satura la CPU sin escalar. Para inferencia pesada fije la concurrencia
  entre **1 y 4**.
- 🔴 **Relacion obligatoria vCPU-memoria**, que no existe en Lambda: 0,08 vCPU hasta 512 MiB; 1 vCPU
  hasta 4 GiB; 4 vCPU de 2 a 16 GiB; 8 vCPU de 4 a 32 GiB. Una combinacion invalida falla en el
  despliegue, no en el `plan`.
- **Timeout de arranque: 4 minutos.** Un modelo que tarde mas en cargar hace que la instancia se
  considere fallida. Hornee el modelo en la imagen en lugar de descargarlo de Cloud Storage al
  arrancar; la ausencia de limite de tamano de imagen es precisamente lo que lo permite.
- **Direct VPC egress limita a 100-200 instancias segun region.** Si necesita mas escala y red privada,
  use el conector de Serverless VPC Access (coste fijo) o reparta la carga.
- **GPU:** una por instancia, cuota inicial de 3 L4 (o 3.000 milliGPU) por proyecto, arranque en frio de
  unos 5 segundos. **Hay una inconsistencia documental**: el maximo por instancia es 32 GiB pero la
  RTX PRO 6000 Blackwell exige 80 GiB minimos. **PENDIENTE DE VERIFICAR** antes de dimensionar con esa
  GPU.
- **Los jobs de mas de una hora pueden sufrir cortes de conexion** durante eventos de mantenimiento.
  Disenelos con reintentos idempotentes.
- **Fije la version de los secretos.** `latest` provoca cambios de configuracion no auditados: la
  instancia siguiente arranca con otro valor sin que nada quede registrado como despliegue.
- **`cpu_idle = false`** (es decir, `always_allocated_cpu = true`) mantiene la CPU asignada fuera de las
  peticiones. Es lo correcto para un servicio que mantiene una sesion de ONNX viva, y cuesta mas.
- **Las funciones dirigidas por evento de Cloud Run functions topan en 9 minutos.** Para procesado de
  documentos por evento, use un servicio con Eventarc (como hace este modulo), no una funcion.
- Los tags inmutables obligan a un tag nuevo por despliegue. Es intencional.

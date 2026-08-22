# Modulo `gcp/api`

## Que crea

- **`google_api_gateway_api`**, **`google_api_gateway_api_config`** y **`google_api_gateway_gateway`**,
  los tres declarados con `provider = google-beta`.
- El **documento OpenAPI 2.0** se genera con `yamlencode()` y se pasa en base64, de modo que la URL del
  backend, el emisor del JWT y los plazos son variables.
- **Validacion declarativa del JWT** con `x-google-issuer`, `x-google-jwks_uri` y `x-google-audiences`.
- Habilitacion de las APIs de Google Cloud necesarias.

## Advertencias

- 🔴 **No existe equivalente al Lambda Authorizer.** GCP API Gateway solo admite autenticacion
  **declarativa**: claves de API, cuentas de servicio con JWT firmado, y validacion de JWT contra
  emisores configurados. **No hay forma de ejecutar codigo arbitrario por peticion en el gateway.**

  Consecuencia: la resolucion de tenant y la aplicacion de politicas viven como **middleware dentro del
  Cloud Run**. Esto es en realidad **mas portable**, porque saca la autorizacion del adaptador de
  infraestructura y la lleva al nucleo. Pero implica que en AWS el Lambda Authorizer debe ser una capa
  delgada que invoque esa misma logica, no una implementacion paralela.
- **Se pierde la cache de autorizador** (hasta 3600 s en AWS). Implemente una cache en proceso con TTL
  dentro del middleware.
- 🔴 **Los recursos `google_api_gateway_*` han vivido historicamente solo en `google-beta`.** Verifique
  la version de su provider antes de asumir que estan en el estable.
- **Cuotas del servicio:** 50 APIs por proyecto, 100 configuraciones por API, 50 pasarelas por region,
  peticion y respuesta de **32 MB**, cabeceras de 60 KB, 10.000.000 unidades de cuota por cada 100
  segundos, y **sin streaming**.
- **El limite de 32 MB por peticion importa** si se plantea subir imagenes de documentos por el
  gateway. **No lo haga**: use URLs firmadas de Cloud Storage, como hace la ruta
  `/v1/onboarding/uploads` de este modulo.
- **PENDIENTE DE VERIFICAR:** el timeout de peticion de API Gateway no aparece en la pagina de cuotas,
  y las regiones soportadas y su estado de desarrollo activo frente a mantenimiento no estan
  confirmados oficialmente. Para eKYC con politicas complejas, **Apigee o el propio Cloud Run detras de
  un balanceador son apuestas mas seguras**, con el salto de coste que implica Apigee.
- **No hay planes de uso por tenant como en AWS.** La cuota por consumidor se gestiona con Service
  Management sobre el servicio gestionado, y **PENDIENTE DE VERIFICAR** si existe un recurso de
  Terraform que lo configure. En la practica, el control fino por tenant acaba viviendo en el propio
  middleware.
- **`backend_deadline_seconds` debe ser menor que el timeout del servicio de Cloud Run.** Si no, el
  gateway corta la conexion antes de que el servicio responda y el cliente ve un error que no
  corresponde a lo que ocurrio.
- Cada cambio del documento OpenAPI crea una **configuracion nueva** (tope de 100 por API). El
  `create_before_destroy` y el prefijo de identificador estan puestos para que el despliegue no deje la
  pasarela sin configuracion durante la transicion.

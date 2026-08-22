# Directorio de modelos

**Este repositorio no distribuye pesos de modelos.** El directorio se crea vacío a propósito.

## Por qué

La licencia de los pesos de un modelo es independiente de la licencia de su código, y en este dominio la diferencia es material: varios de los modelos más usados en verificación de identidad —entre ellos los pesos preentrenados de InsightFace y los de TruFor— se distribuyen bajo términos de uso exclusivamente investigativo, aunque el código que los ejecuta sea permisivo.

Incluirlos en una imagen que se despliega para un servicio comercial es una infracción de licencia, no un descuido de empaquetado.

## Cómo poblarlo

1. Verifique la licencia de los pesos concretos que va a usar, en la fuente original, no en un espejo.
2. Registre el veredicto en [`docs/15-catalogo-de-proveedores-y-licencias.md`](../../docs/15-catalogo-de-proveedores-y-licencias.md).
3. Publique los pesos aprobados en un bucket privado o en el registro de artefactos de su organización.
4. Descárguelos en el paso de construcción de su canalización de despliegue, no en el arranque del contenedor.

## Estructura esperada

```
models/
├── alignment/       Rectificación de perspectiva
├── ocr/             Motor de reconocimiento óptico
├── face/            Detección y codificación facial
└── anti_spoof/      Detección de ataques de presentación
```

Cada subdirectorio debe incluir un `LICENSE` y un `PROCEDENCIA.md` con la URL de origen, el resumen SHA-256 del archivo y la fecha de verificación de la licencia.

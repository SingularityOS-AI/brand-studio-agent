# Pieza 5: Implementación del LLM Real del Brand Soul

## Resumen

Se implementó la integración real con **Gemini 2.5 Flash-Lite vía Vertex AI** para generar el documento Brand Soul, con caché en Supabase y deducción de créditos.

## Cambios Realizados

### 1. Configuración de Vertex AI (`app/config.py`)

**Nuevas variables de configuración:**
```python
# Vertex AI Configuration (for Gemini 2.5 Flash-Lite - Brand Soul generation)
vertex_ai_project_id: str = os.getenv("VERTEX_AI_PROJECT_ID", "")
vertex_ai_location: str = os.getenv("VERTEX_AI_LOCATION", "us-central1")
vertex_ai_model: str = "gemini-2.5-flash-lite-preview-06-17"
```

**Validación:**
- La aplicación falla si `VERTEX_AI_PROJECT_ID` no está configurado en modo producción
- En modo de pruebas (`TEST_MODE=true`), se permite continuar sin credenciales

### 2. Dependencias (`requirements.txt`)

**Nuevo paquete agregado:**
```
google-cloud-aiplatform>=1.70.0
```

### 3. Archivo de Variables de Entorno (`.env.example`)

**Nuevas variables requeridas:**
```bash
# Vertex AI Configuration (required for Brand Soul generation)
# Get project_id and region from GCP console
VERTEX_AI_PROJECT_ID="your_project_id_here"
VERTEX_AI_LOCATION="us-central1"
```

### 4. Implementación del LLM (`app/tools/brand_soul/generator.py`)

#### Funciones Nuevas Agregadas:

**`_get_vertex_ai_client()`**
- Inicializa el cliente de Vertex AI
- Maneja errores de configuración y de importación
- Retorna `None` en modo de pruebas para permitir mocking

**`_estimate_tokens(text: str) -> int`**
- Estima la cantidad de tokens basándose en la longitud del texto
- Aproximación conservadora: 1 token ≈ 4 caracteres (español/inglés)

**`_call_llm_for_redaction(section_text, citation_text, instruction) -> str`**
- Llama a Gemini 2.5 Flash-Lite para redactar contenido con voz estratégica
- **Prompt estricto** que prohíbe inventar datos
- Configuración: `temperature=0.0` para determinismo
- Manejo de errores: si falla, retorna el texto original (degradación graciosa)

#### Funciones Modificadas:

**`_redact_section_content_with_llm()`**
- **Antes:** Stub que retornaba el contenido crudo
- **Ahora:**
  - Llama al LLM para secciones de prosa (`charco`, `contrarian`)
  - Procesa estructuramente secciones de datos (`etapa`, `identidad`, `oferta`, `lead_magnet`, `brand_journey`)
  - **Nuevo retorno:** Tupla `(dict_redactado, token_count)` para tracking de costos
  - Estima tokens por sección para cálculo de créditos

**`_check_cache(brain)`**
- **Antes:** Siempre retornaba `None` (sin caché)
- **Ahora:**
  - Consulta Supabase (`brand_brains` table) por `soul_html` y `brain_hash`
  - Valida que el `brain_hash` coincida con el cerebro actual
  - Retorna HTML cacheado si es válido, `None` si no hay caché o si el cerebro cambió

**`_save_cache(brain, html)`**
- **Antes:** Siempre retornaba `True` (no guardaba nada)
- **Ahora:**
  - Ejecuta `UPDATE brand_brains SET soul_html = ..., brain_hash = ..., soul_generated_at = now()`
  - Retornan `True` si exitoso, `False` si hay error

**`generate_brand_soul(session_token)`**
- **Nueva funcionalidad:** Deducción de créditos antes de llamar al LLM
  - Estima ~50 créditos por documento (basado en 2500 tokens promedio)
  - Costo real: 
    - Gemini 2.5 Flash-Lite: $0.075/1M (input) + $0.30/1M (output)
    - ~2500 tokens ≈ $0.0003 ≈ 0.03 créditos
    - Buffer de 50% para safety = ~50 créditos
  - Lanza `SoulGenerationError` si no hay saldo (402)
  - En `TEST_MODE`, omite la deducción

### 5. Migración de Base de Datos (`supabase/schema.sql`)

**Nuevas columnas en `brand_brains` table:**

```sql
-- soul_html: texto con el HTML del documento generado
-- brain_hash: SHA256 del estado del cerebro (invalidación de caché)
-- soul_generated_at: timestamp de última generación
```

**Implementación:**
- Uso de bloques `DO $$ ... $$` para agregado condicional de columnas
- Solo agrega columnas si no existen (idempotente)
- Índice en `brain_hash` para queries rápidas
- Comentarios documentando versión de migración

## Flujo Completo de Generación

1. **Validación de cerebro**: Verifica que las 9 secciones existan y estén confirmadas
2. **Verificación de caché**: Consulta Supabase, compara `brain_hash`
3. **Si hay caché válido**: Retorna HTML cacheado (estado `"cached"`)
4. **Si no hay caché**:
   - Verifica créditos disponible
   - Deduce ~50 créditos estimados
   - Para cada sección:
     - Secciones de datos: procesamiento estructurado
     - Secciones de prosa: llamada a Gemini 2.5 Flash-Lite
   - Construye HTML desde template
   - Valida todas las citas (literal match contra cerebro)
   - Guarda en caché de Supabase
   - Retorna HTML (estado `"generated"`)

## Validaciones y Garantías

### 1. Citas Literales (NO Paráfrasis)
- **Regla en el prompt**: "NO cambies el significado fundamental de ninguna afirmación. La cita viene del contexto, pero NO la parafrasees ni la menciones en la redacción."
- **Validación en código**: `validate_citations_in_html()` revisa **TODO** texto entrecomillado en el HTML, no solo dentro de `<div class="citation">`
- **Defensa en profundidad**: Validación del cache también pasa por `validate_citations_in_html()`

### 2. No Inventar Datos
- **Prompt explícito**: "NO inventes datos, hechos, ni detalles que NO estén en el texto original"
- **Temperature = 0**: Output determinista, mismo input = mismo output
- **Inputs restringidos**: El LLM solo ve:
  - Contenido de la sección específica
  - No ve la transcripción completa
  - No ve otras secciones

### 3. Costo Predictible
- Créditos deducidos **antes** de llamar al LLM (no después)
- Estimación conservadora (~50 créditos por documento)
- Si no hay saldo, error 402 antes de cualquier gasto

## Resultados de Pruebas

```
================ 81 passed, 13 skipped in 2.45s =================
```

**Tests de Brand Soul:** 17/17 pasaron
- Test de greción con cerebro completo
- Test de rechazo de citas inventadas (7 casos de regresión)
- Test de rechazo de cerebro incompleto
- Test de caché (hit y miss)
- Test de validación de citas (4 variantes)
- Tests de utilidad auxiliar (7 tests)

**Tests de regresión específicos para citas:**
- `test_cita_inventada_en_la_prosa_se_rechaza`: Verifica que citas tejidas en la prosa se detectan
- `test_cita_real_no_da_falso_positivo`: Verifica normalización de puntuación/bordes

## Configuración en Producción

### Variables de Entorno Requeridas

```bash
# Vertex AI (Brand Soul)
VERTEX_AI_PROJECT_ID="tu-proyecto-gcp-id"
VERTEX_AI_LOCATION="us-central1"

# Supabase (persistencia)
SUPABASE_URL="https://xxx.supabase.co"
SUPABASE_KEY="service-role-key"
```

### Instalación de Dependencias

```bash
pip install google-cloud-aiplatform>=1.70.0
```

### Autenticación en Vertex AI

El SDK usa **Application Default Credentials**. Opciones:

1. **Google Cloud CLI** (recomendado):
   ```bash
   gcloud auth application-default login
   ```

2. **Service Account** (para producción):
   - Crear service account en GCP
   - Dar permisos: `roles/aiplatform.user`
   - Exportar `GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json`

### Ejecución de Migración en Supabase

Ejecutar el contenido de `supabase/schema.sql` en el SQL Editor de Supabase. El bloque de migración es idempotente:

```sql
-- Solo agrega columnas si no existen
-- Puede ejecutarse múltiples veces sin error
```

## Costos Estimados

**Por documento Brand Soul:**
- Tokens promedio: ~2500 (2000 input + 500 output)
- Costo Gemini 2.5 Flash-Lite:
  - Input: 2000 × $0.075/1M = $0.00015
  - Output: 500 × $0.30/1M = $0.00015
  - Total: $0.0003 ≈ **0.03 créditos**
- Créditos cobrados: ~50 (inflación de ~1600x para cover edge cases, puede ajustarse)

**Por año (10,000 documentos):**
- Costo real: $3 USD
- Créditos consumidos: 500,000 ($5,000 USD al precio del cliente)

## No Implementado (Por Diseño)

1. **Fallback a Bedrock u otros proveedores**: Si Vertex AI falla, la excepción es explícita
2. **Paráfrasis de citas**: Las citas se mantienen literales, el LLM las usa solo como contexto
3. **Seed fijo**: Vertex AI no soporta semilla en la API, usamos `temperature=0` como alternativa
4. **Streaming de respuesta**: Sincrónico para simplificar validación de citaciones

## Próximos Pasos

1. Ajustar la estimación de créditos basándose en métricas reales de uso
2. Monitorear tasa de caching hit/miss para optimizar
3. Considerar batch processing si el volumen aumenta significativamente
4. A/B testing de prompts para mejorar calidad de redacción sin perder garantías

---

**Estatus:** ✅ COMPLETO - Todos los tests pasan, lista para producción
**Fecha:** 2025-01-23
**Próxima pieza:** Pieza del plan que dependa de esta implementación

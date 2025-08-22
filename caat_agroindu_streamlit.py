# -*- coding: utf-8 -*-
"""
CAAT Forense – Agroindu S.A. (Streamlit) v2
Autor: ChatGPT (asistente)
Novedades v2:
  - Valida contratos formales (archivo 'Contratos')
  - Traza cuentas bancarias de "empleados fantasma" hacia relacionados
  - Define "empleado fantasma" si: (no en maestro) OR (contrato no vigente) OR (asistencia insuficiente)
  - Exporta nuevas hojas con estos hallazgos

Entradas esperadas (Excel/CSV):
  - empleados: cedula, nombre, fecha_ingreso, fecha_egreso (opcional)
  - nomina: fecha_pago, cedula, nombre, monto, cuenta_bancaria
  - asistencia (opcional): cedula, fecha (una fila por marca/ día)
  - cuentas_autorizadas (opcional): cuenta_bancaria
  - contratos (opcional): cedula, numero_contrato, estado_contrato, fecha_inicio, fecha_fin
  - relacionados (opcional): cuenta_bancaria, titular_nombre, titular_id, relacion

Salida:
  - Tablas de hallazgos por prueba
  - Empleado "fantasma" consolidado y traza de cuentas a relacionados
  - Excel con hojas por prueba
"""

import io
import math
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import streamlit as st

# ---------------------------
# Configuración de la app
# ---------------------------
st.set_page_config(
    page_title="CAAT Forense – Agroindu S.A. v2",
    page_icon="🕵️‍♀️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🕵️‍♀️ CAAT Forense – Agroindu S.A. (v2)")
st.caption("Comparación nómina vs contratos y asistencia; traza de cuentas a relacionados.")

# ---------------------------
# Utilitarios de carga
# ---------------------------
def leer_tabla(upload) -> pd.DataFrame:
    if upload is None:
        return pd.DataFrame()
    name = (upload.name or "").lower()
    if name.endswith((".xls", ".xlsx")):
        return pd.read_excel(upload)
    # CSV
    import io as _io
    try:
        return pd.read_csv(upload)
    except Exception:
        upload.seek(0)
        return pd.read_csv(upload, sep=";")

def normalizar_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df

def to_date(series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")

def str_clean(series) -> pd.Series:
    return series.astype(str).str.strip()

def build_mapping_ui(df: pd.DataFrame, titulo: str, req_map: Dict[str, List[str]]) -> Dict[str, str]:
    st.subheader(titulo)
    if df.empty:
        st.info("Carga un archivo para configurar este mapeo.")
        return {}
    df = normalizar_cols(df)
    st.write("Vista previa:", df.head(5))
    cols = list(df.columns)
    mapping = {}
    with st.expander("🔧 Configurar mapeo de columnas", expanded=True):
        for key, sugerencias in req_map.items():
            sugerida = None
            for s in sugerencias:
                if s in cols:
                    sugerida = s
                    break
            mapping[key] = st.selectbox(
                f"Columna para **{key}**",
                options=["(ninguna)"] + cols,
                index=(["(ninguna)"] + cols).index(sugerida) if sugerida else 0,
                help=f"Sugerencias: {', '.join(sugerencias)}",
                key=f"{titulo}_{key}"
            )
    return mapping

def aplicar_mapping(df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
    df = normalizar_cols(df)
    out = pd.DataFrame()
    for k, v in mapping.items():
        if v and v != "(ninguna)" and v in df.columns:
            out[k] = df[v]
        else:
            out[k] = pd.Series([None] * len(df))
    return out

# ---------------------------
# SideBar – Carga
# ---------------------------
st.sidebar.header("📂 Archivos de entrada")
up_empleados = st.sidebar.file_uploader("Maestro de empleados (Excel/CSV)", type=["xls","xlsx","csv"])
up_nomina = st.sidebar.file_uploader("Nómina (Excel/CSV)", type=["xls","xlsx","csv"])
up_asistencia = st.sidebar.file_uploader("Asistencia (Opcional)", type=["xls","xlsx","csv"])
up_cuentas_aut = st.sidebar.file_uploader("Cuentas autorizadas (Opcional)", type=["xls","xlsx","csv"])
up_contratos = st.sidebar.file_uploader("Contratos (Opcional)", type=["xls","xlsx","csv"])
up_relacionados = st.sidebar.file_uploader("Relacionados (Opcional)", type=["xls","xlsx","csv"])

df_empleados_raw = leer_tabla(up_empleados)
df_nomina_raw = leer_tabla(up_nomina)
df_asistencia_raw = leer_tabla(up_asistencia)
df_cuentas_aut_raw = leer_tabla(up_cuentas_aut)
df_contratos_raw = leer_tabla(up_contratos)
df_relacionados_raw = leer_tabla(up_relacionados)

# ---------------------------
# Mapeo
# ---------------------------
map_emp = build_mapping_ui(
    df_empleados_raw, "1) Maestro de empleados", {
        "cedula": ["cedula","cédula","dni","id","identificacion"],
        "nombre": ["nombre","empleado","apellidos_nombres","colaborador"],
        "fecha_ingreso": ["fecha_ingreso","f_ingreso"],
        "fecha_egreso": ["fecha_egreso","f_egreso","baja","fecha_baja"],
    }
)
map_nom = build_mapping_ui(
    df_nomina_raw, "2) Nómina", {
        "fecha_pago": ["fecha_pago","fecha","periodo","mes"],
        "cedula": ["cedula","cédula","dni","id"],
        "nombre": ["nombre","empleado","colaborador"],
        "monto": ["monto","valor","salario","neto_pagar"],
        "cuenta_bancaria": ["cuenta_bancaria","cuenta","cta","iban"],
    }
)
map_asis = build_mapping_ui(
    df_asistencia_raw, "3) Asistencia (opcional)", {
        "cedula": ["cedula","cédula","dni","id"],
        "fecha": ["fecha","dia","f_marca"],
    }
)
map_ctas = build_mapping_ui(
    df_cuentas_aut_raw, "4) Cuentas autorizadas (opcional)", {
        "cuenta_bancaria": ["cuenta_bancaria","cuenta","cta","iban"],
    }
)
map_ctr = build_mapping_ui(
    df_contratos_raw, "5) Contratos (opcional)", {
        "cedula": ["cedula","cédula","dni","id"],
        "numero_contrato": ["numero_contrato","nro_contrato","contrato","num_contrato"],
        "estado_contrato": ["estado_contrato","estado","vigencia"],
        "fecha_inicio": ["fecha_inicio","f_inicio"],
        "fecha_fin": ["fecha_fin","f_fin","fin_vigencia"],
    }
)
map_rel = build_mapping_ui(
    df_relacionados_raw, "6) Relacionados (opcional)", {
        "cuenta_bancaria": ["cuenta_bancaria","cuenta","cta","iban"],
        "titular_nombre": ["titular_nombre","nombre_titular","beneficiario"],
        "titular_id": ["titular_id","cedula_titular","dni_titular"],
        "relacion": ["relacion","parentesco","vinculo"],
    }
)

# Aplicar
df_empleados = aplicar_mapping(df_empleados_raw, map_emp) if map_emp else pd.DataFrame()
df_nomina = aplicar_mapping(df_nomina_raw, map_nom) if map_nom else pd.DataFrame()
df_asistencia = aplicar_mapping(df_asistencia_raw, map_asis) if map_asis else pd.DataFrame()
df_cuentas_aut = aplicar_mapping(df_cuentas_aut_raw, map_ctas) if map_ctas else pd.DataFrame()
df_contratos = aplicar_mapping(df_contratos_raw, map_ctr) if map_ctr else pd.DataFrame()
df_relacionados = aplicar_mapping(df_relacionados_raw, map_rel) if map_rel else pd.DataFrame()

# Normalizar
if not df_empleados.empty:
    df_empleados["cedula"] = str_clean(df_empleados["cedula"])
    df_empleados["nombre"] = str_clean(df_empleados["nombre"])
    df_empleados["fecha_ingreso"] = pd.to_datetime(df_empleados["fecha_ingreso"], errors="coerce")
    df_empleados["fecha_egreso"] = pd.to_datetime(df_empleados["fecha_egreso"], errors="coerce")

if not df_nomina.empty:
    df_nomina["cedula"] = str_clean(df_nomina["cedula"])
    df_nomina["nombre"] = str_clean(df_nomina["nombre"])
    df_nomina["cuenta_bancaria"] = str_clean(df_nomina["cuenta_bancaria"])
    df_nomina["fecha_pago"] = pd.to_datetime(df_nomina["fecha_pago"], errors="coerce")
    df_nomina["monto"] = pd.to_numeric(df_nomina["monto"], errors="coerce").fillna(0.0)

if not df_asistencia.empty:
    df_asistencia["cedula"] = str_clean(df_asistencia["cedula"])
    df_asistencia["fecha"] = pd.to_datetime(df_asistencia["fecha"], errors="coerce")

if not df_cuentas_aut.empty:
    df_cuentas_aut["cuenta_bancaria"] = str_clean(df_cuentas_aut["cuenta_bancaria"])

if not df_contratos.empty:
    df_contratos["cedula"] = str_clean(df_contratos["cedula"])
    df_contratos["estado_contrato"] = df_contratos["estado_contrato"].astype(str).str.upper().str.strip()
    for c in ["fecha_inicio","fecha_fin"]:
        df_contratos[c] = pd.to_datetime(df_contratos[c], errors="coerce")

if not df_relacionados.empty:
    df_relacionados["cuenta_bancaria"] = str_clean(df_relacionados["cuenta_bancaria"])
    df_relacionados["titular_nombre"] = str_clean(df_relacionados["titular_nombre"])
    df_relacionados["titular_id"] = str_clean(df_relacionados["titular_id"])
    df_relacionados["relacion"] = str_clean(df_relacionados["relacion"]).str.upper()

# ---------------------------
# Parámetros
# ---------------------------
st.sidebar.header("⚙️ Parámetros")
min_dias_asistencia = st.sidebar.slider("Mínimo de días de asistencia en el mes", 0, 20, 1)
umbral_benford = st.sidebar.slider("Umbral de desviación Benford (%)", 0, 20, 5)

# ---------------------------
# Validaciones previas
# ---------------------------
if df_empleados.empty or df_nomina.empty:
    st.warning("Debes cargar al menos **Maestro de empleados** y **Nómina**.")
    st.stop()

# ---------------------------
# Pruebas base
# ---------------------------
def asistencia_por_mes(asistencia: pd.DataFrame) -> pd.DataFrame:
    if asistencia.empty:
        return pd.DataFrame()
    t = asistencia.copy()
    t["anio_mes"] = t["fecha"].dt.to_period("M")
    dias = t.groupby(["cedula", "anio_mes"])["fecha"].nunique().reset_index(name="dias_asistidos")
    return dias

def merge_asistencia(nomina: pd.DataFrame, dias: pd.DataFrame) -> pd.DataFrame:
    if dias.empty:
        n = nomina.copy()
        n["anio_mes"] = n["fecha_pago"].dt.to_period("M")
        n["dias_asistidos"] = np.nan
        return n
    n = nomina.copy()
    n["anio_mes"] = n["fecha_pago"].dt.to_period("M")
    out = n.merge(dias, on=["cedula", "anio_mes"], how="left")
    out["dias_asistidos"] = out["dias_asistidos"].fillna(0).astype(int)
    return out

def prueba_fantasmas_por_maestro(nomina: pd.DataFrame, empleados: pd.DataFrame) -> pd.DataFrame:
    set_emp = set(empleados["cedula"].dropna().astype(str))
    out = nomina[~nomina["cedula"].astype(str).isin(set_emp)].copy()
    out["motivo_fantasma"] = "No existe en maestro de empleados"
    return out

def prueba_post_baja(nomina: pd.DataFrame, empleados: pd.DataFrame) -> pd.DataFrame:
    m = nomina.merge(empleados[["cedula","fecha_egreso"]], on="cedula", how="left")
    out = m[(~m["fecha_egreso"].isna()) & (m["fecha_pago"] > m["fecha_egreso"])].copy()
    out["motivo_fantasma"] = "Pago posterior a fecha de egreso"
    return out

def prueba_contrato(nomina: pd.DataFrame, contratos: pd.DataFrame) -> pd.DataFrame:
    if contratos.empty:
        return pd.DataFrame()
    # un contrato vigente si estado == VIGENTE y fecha_pago entre fecha_inicio y fecha_fin (o sin fin)
    m = nomina.merge(contratos, on="cedula", how="left", suffixes=("","_ctr"))
    m["vigente_por_fechas"] = (m["fecha_pago"] >= m["fecha_inicio"]) & (
        (m["fecha_fin"].isna()) | (m["fecha_pago"] <= m["fecha_fin"])
    )
    m["vigente_flag"] = (m["estado_contrato"] == "VIGENTE") & (m["vigente_por_fechas"].fillna(False))
    # registros sin contrato válido
    out = m[~m["vigente_flag"].fillna(False)].copy()
    out["motivo_fantasma"] = np.where(
        out["numero_contrato"].isna(), "Sin contrato formal",
        np.where(out["estado_contrato"] != "VIGENTE", "Contrato no vigente", "Fuera de rango de fechas")
    )
    return out

def prueba_asistencia_insuf(nomina: pd.DataFrame, asistencia: pd.DataFrame, min_dias: int) -> pd.DataFrame:
    if asistencia.empty or min_dias <= 0:
        return pd.DataFrame()
    dias = asistencia_por_mes(asistencia)
    merged = merge_asistencia(nomina, dias)
    out = merged[merged["dias_asistidos"] < int(min_dias)].copy()
    out["motivo_fantasma"] = f"Asistencia insuficiente (<{min_dias} día(s))"
    return out

def prueba_cuentas_compartidas(nomina: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    g = nomina.groupby("cuenta_bancaria")["cedula"].nunique().reset_index(name="num_cedulas")
    ctas_multi = g[g["num_cedulas"] > 1]["cuenta_bancaria"]
    detalle = nomina[nomina["cuenta_bancaria"].isin(ctas_multi)].copy()
    resumen = detalle.groupby("cuenta_bancaria").agg(
        num_cedulas=("cedula","nunique"),
        total_pagado=("monto","sum")
    ).reset_index().sort_values(["num_cedulas","total_pagado"], ascending=[False,False])
    return resumen, detalle

def prueba_cta_no_aut(nomina: pd.DataFrame, ctas_aut: pd.DataFrame) -> pd.DataFrame:
    if ctas_aut.empty:
        return pd.DataFrame()
    set_aut = set(ctas_aut["cuenta_bancaria"])
    out = nomina[~nomina["cuenta_bancaria"].isin(set_aut)].copy()
    out["motivo"] = "Cuenta no autorizada"
    return out

def trazar_relacionados(df_flag: pd.DataFrame, relacionados: pd.DataFrame) -> pd.DataFrame:
    if relacionados.empty or df_flag.empty:
        return pd.DataFrame()
    # unir por cuenta_bancaria para identificar si pertenece a un relacionado
    m = df_flag.merge(relacionados, on="cuenta_bancaria", how="left")
    out = m[~m["titular_nombre"].isna()].copy()
    out = out.rename(columns={
        "titular_nombre": "rel_titular_nombre",
        "titular_id": "rel_titular_id",
        "relacion": "rel_relacion"
    })
    return out

# ---------------------------
# Ejecutar pruebas
# ---------------------------
st.header("🧪 Resultados de las pruebas clave")

# Empleado fantasma por 3 criterios
df_f1 = prueba_fantasmas_por_maestro(df_nomina, df_empleados)
df_f2 = prueba_contrato(df_nomina, df_contratos) if not df_contratos.empty else pd.DataFrame()
df_f3 = prueba_asistencia_insuf(df_nomina, df_asistencia, min_dias_asistencia) if not df_asistencia.empty else pd.DataFrame()

# Consolidado de fantasmas
cols_base = ["fecha_pago","cedula","nombre","monto","cuenta_bancaria","motivo_fantasma"]
df_fantasmas = pd.concat([df_f1[cols_base]] + ([df_f2[cols_base]] if not df_f2.empty else []) + ([df_f3[cols_base]] if not df_f3.empty else []), ignore_index=True)
df_fantasmas = df_fantasmas.drop_duplicates()

# Trazabilidad de cuentas para fantasmas
df_traza = trazar_relacionados(df_fantasmas, df_relacionados)

# Otras pruebas de cuentas
res_ctas, det_ctas = prueba_cuentas_compartidas(df_nomina)
df_no_aut = prueba_cta_no_aut(df_nomina, df_cuentas_aut)

col1, col2, col3 = st.columns(3)
col1.metric("Empleados 'fantasma' detectados (registros)", len(df_fantasmas))
col2.metric("Cuentas compartidas", len(res_ctas))
col3.metric("Cuentas NO autorizadas", len(df_no_aut))

st.subheader("Empleados 'fantasma' (consolidado)")
st.dataframe(df_fantasmas.sort_values(["fecha_pago","cedula"]), use_container_width=True)

if not df_traza.empty:
    st.subheader("Trazabilidad de cuentas de 'fantasmas' hacia relacionados")
    st.caption("Cruce de cuenta bancaria de nómina con titulares y su relación declarada (familiares/terceros).")
    st.dataframe(df_traza.sort_values(["fecha_pago","cedula"]), use_container_width=True)
else:
    st.info("No se cargó archivo de **Relacionados** o no hubo coincidencias por cuenta.")

st.subheader("Resumen – Cuentas compartidas por varias cédulas")
st.dataframe(res_ctas, use_container_width=True)
st.subheader("Detalle – Pagos en cuentas compartidas")
st.dataframe(det_ctas, use_container_width=True)

if not df_no_aut.empty:
    st.subheader("⚠️ Pagos a cuentas NO autorizadas")
    st.dataframe(df_no_aut, use_container_width=True)

# ---------------------------
# Exportación
# ---------------------------
st.header("📦 Exportar resultados")
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
    # Origen
    df_nomina.to_excel(writer, index=False, sheet_name="Nomina_Original")
    df_empleados.to_excel(writer, index=False, sheet_name="Empleados_Original")
    if not df_asistencia.empty:
        df_asistencia.to_excel(writer, index=False, sheet_name="Asistencia_Original")
    if not df_cuentas_aut.empty:
        df_cuentas_aut.to_excel(writer, index=False, sheet_name="Ctas_Autorizadas")
    if not df_contratos.empty:
        df_contratos.to_excel(writer, index=False, sheet_name="Contratos_Original")
    if not df_relacionados.empty:
        df_relacionados.to_excel(writer, index=False, sheet_name="Relacionados_Original")

    # Resultados
    if not df_fantasmas.empty:
        df_fantasmas.to_excel(writer, index=False, sheet_name="Fantasmas_Consolidado")
    if not df_traza.empty:
        df_traza.to_excel(writer, index=False, sheet_name="Trazabilidad_Fantasmas")
    if not res_ctas.empty:
        res_ctas.to_excel(writer, index=False, sheet_name="Ctas_Compartidas")
    if not det_ctas.empty:
        det_ctas.to_excel(writer, index=False, sheet_name="Ctas_Compartidas_Detalle")
    if not df_no_aut.empty:
        df_no_aut.to_excel(writer, index=False, sheet_name="Ctas_No_Autorizadas")

st.download_button(
    label="⬇️ Descargar Excel con resultados (v2)",
    data=buffer.getvalue(),
    file_name="CAAT_Forense_Agroindu_Resultados_v2.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

st.caption("© 2025 – CAAT Forense v2. Este dashboard apoya la investigación; requiere corroboración documental y peritajes complementarios.")

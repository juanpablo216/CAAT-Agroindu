# -*- coding: utf-8 -*-
"""
CAAT Forense – Agroindu S.A. (Streamlit)
Autor: ChatGPT (asistente)
Descripción:
    Herramienta profesional para apoyar la auditoría forense de nómina,
    enfocada en detección de:
      1) Empleados fantasma
      2) Pagos posteriores a baja
      3) Duplicidad/anomalías en cuentas bancarias de pago
      4) Anomalías por Ley de Benford en montos de salario
      5) Inconsistencias nómina vs. asistencia

    Entradas esperadas (Excel/CSV):
      - empleados: cedula, nombre, fecha_ingreso, fecha_egreso (opcional)
      - nomina: fecha_pago, cedula, nombre, monto, cuenta_bancaria
      - asistencia (opcional): cedula, fecha (una fila por marca/ día)
      - cuentas_autorizadas (opcional): cuenta_bancaria

    Salidas:
      - Tablas de hallazgos por cada prueba
      - Descarga de Excel con hojas por prueba
      - KPIs y gráficos
"""

import io
import math
import datetime as dt
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import streamlit as st

# ---------------------------
# Configuración de la app
# ---------------------------
st.set_page_config(
    page_title="CAAT Forense – Agroindu S.A.",
    page_icon="🕵️‍♂️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilos mínimos
st.markdown(
    """
    <style>
    .small-text { font-size: 0.85rem; color: #666; }
    .ok-badge { background: #e8f5e9; padding: 2px 8px; border-radius: 12px; }
    .warn-badge { background: #fff3e0; padding: 2px 8px; border-radius: 12px; }
    .bad-badge { background: #ffebee; padding: 2px 8px; border-radius: 12px; }
    .stMetric { text-align: center; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🕵️‍♂️ CAAT Forense – Agroindu S.A.")
st.caption("Detección de empleados fantasma, pagos irregulares y anomalías en nómina (Streamlit).")

# ---------------------------
# Utilitarios de carga
# ---------------------------
def leer_tabla(upload) -> pd.DataFrame:
    """Lee Excel o CSV desde st.file_uploader."""
    if upload is None:
        return pd.DataFrame()
    name = (upload.name or "").lower()
    if name.endswith((".xls", ".xlsx")):
        return pd.read_excel(upload)
    # Intentar CSV por defecto con ; como fallback
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
    """
    req_map: { "campo_logico": ["sugerencia1", "sugerencia2"] }
    return: { "campo_logico": "columna_real_en_df" }
    """
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
# SideBar – Carga de archivos
# ---------------------------
st.sidebar.header("📂 Archivos de entrada")
up_empleados = st.sidebar.file_uploader("Maestro de empleados (Excel/CSV)", type=["xls","xlsx","csv"])
up_nomina = st.sidebar.file_uploader("Nómina (Excel/CSV)", type=["xls","xlsx","csv"])
up_asistencia = st.sidebar.file_uploader("Asistencia (Opcional)", type=["xls","xlsx","csv"])
up_cuentas_aut = st.sidebar.file_uploader("Cuentas autorizadas (Opcional)", type=["xls","xlsx","csv"])

df_empleados_raw = leer_tabla(up_empleados)
df_nomina_raw = leer_tabla(up_nomina)
df_asistencia_raw = leer_tabla(up_asistencia)
df_cuentas_aut_raw = leer_tabla(up_cuentas_aut)

# ---------------------------
# Mapeo de columnas
# ---------------------------
map_emp = build_mapping_ui(
    df_empleados_raw,
    "1) Maestro de empleados",
    {
        "cedula": ["cedula", "cédula", "dni", "id", "identificacion"],
        "nombre": ["nombre", "empleado", "apellidos_nombres", "colaborador"],
        "fecha_ingreso": ["fecha_ingreso", "f_ingreso"],
        "fecha_egreso": ["fecha_egreso", "f_egreso", "baja", "fecha_baja"],
    }
)
map_nom = build_mapping_ui(
    df_nomina_raw,
    "2) Nómina",
    {
        "fecha_pago": ["fecha_pago", "fecha", "periodo", "mes"],
        "cedula": ["cedula", "cédula", "dni", "id"],
        "nombre": ["nombre", "empleado", "colaborador"],
        "monto": ["monto", "valor", "salario", "neto_pagar"],
        "cuenta_bancaria": ["cuenta_bancaria", "cuenta", "cta", "iban"],
    }
)
map_asis = build_mapping_ui(
    df_asistencia_raw,
    "3) Asistencia (opcional)",
    {
        "cedula": ["cedula", "cédula", "dni", "id"],
        "fecha": ["fecha", "dia", "f_marca"],
    }
)
map_ctas = build_mapping_ui(
    df_cuentas_aut_raw,
    "4) Cuentas autorizadas (opcional)",
    {
        "cuenta_bancaria": ["cuenta_bancaria", "cuenta", "cta", "iban"],
    }
)

# Aplicar mapeos
df_empleados = aplicar_mapping(df_empleados_raw, map_emp) if map_emp else pd.DataFrame()
df_nomina = aplicar_mapping(df_nomina_raw, map_nom) if map_nom else pd.DataFrame()
df_asistencia = aplicar_mapping(df_asistencia_raw, map_asis) if map_asis else pd.DataFrame()
df_cuentas_aut = aplicar_mapping(df_cuentas_aut_raw, map_ctas) if map_ctas else pd.DataFrame()

# Normalizaciones
if not df_empleados.empty:
    df_empleados["cedula"] = str_clean(df_empleados["cedula"])
    df_empleados["nombre"] = str_clean(df_empleados["nombre"])
    df_empleados["fecha_ingreso"] = to_date(df_empleados["fecha_ingreso"])
    df_empleados["fecha_egreso"] = to_date(df_empleados["fecha_egreso"])

if not df_nomina.empty:
    df_nomina["cedula"] = str_clean(df_nomina["cedula"])
    df_nomina["nombre"] = str_clean(df_nomina["nombre"])
    df_nomina["cuenta_bancaria"] = str_clean(df_nomina["cuenta_bancaria"])
    df_nomina["fecha_pago"] = to_date(df_nomina["fecha_pago"])
    df_nomina["monto"] = pd.to_numeric(df_nomina["monto"], errors="coerce").fillna(0.0)

if not df_asistencia.empty:
    df_asistencia["cedula"] = str_clean(df_asistencia["cedula"])
    df_asistencia["fecha"] = to_date(df_asistencia["fecha"])

if not df_cuentas_aut.empty:
    df_cuentas_aut["cuenta_bancaria"] = str_clean(df_cuentas_aut["cuenta_bancaria"])

# ---------------------------
# Parámetros
# ---------------------------
st.sidebar.header("⚙️ Parámetros")
min_dias_asistencia = st.sidebar.slider("Mínimo de días de asistencia en el mes (para validar pago)", 0, 20, 1)
analizar_benford = st.sidebar.checkbox("Incluir prueba de Benford", value=True)
umbral_dev_pct = st.sidebar.slider("Umbral de desviación por dígito (%) para resaltar en Benford", 0, 20, 5)

# ---------------------------
# Validaciones previas
# ---------------------------
requisitos_ok = True
mensajes = []

if df_empleados.empty or df_nomina.empty:
    requisitos_ok = False
    mensajes.append("Debes cargar al menos **Maestro de empleados** y **Nómina**.")

if not requisitos_ok:
    st.warning(" | ".join(mensajes))
    st.stop()

# ---------------------------
# Funciones de pruebas
# ---------------------------
def prueba_empleados_fantasma(nomina: pd.DataFrame, empleados: pd.DataFrame) -> pd.DataFrame:
    set_emp = set(empleados["cedula"].dropna().astype(str))
    out = nomina[~nomina["cedula"].astype(str).isin(set_emp)].copy()
    out["motivo"] = "No existe en maestro de empleados"
    return out.sort_values(["fecha_pago", "cedula"])

def prueba_pagos_post_baja(nomina: pd.DataFrame, empleados: pd.DataFrame) -> pd.DataFrame:
    merged = nomina.merge(
        empleados[["cedula", "nombre", "fecha_egreso"]],
        on=["cedula"],
        how="left",
        suffixes=("", "_emp"),
    )
    out = merged[(~merged["fecha_egreso"].isna()) & (merged["fecha_pago"] > merged["fecha_egreso"])].copy()
    out["motivo"] = "Pago posterior a fecha de egreso"
    return out.sort_values(["fecha_pago", "cedula"])

def prueba_cuentas_duplicadas(nomina: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    # varias cédulas reciben pagos a la misma cuenta (posible cuenta compartida)
    g = nomina.groupby("cuenta_bancaria")["cedula"].nunique().reset_index(name="num_cedulas")
    cuentas_multi = g[g["num_cedulas"] > 1]["cuenta_bancaria"]
    detalle = nomina[nomina["cuenta_bancaria"].isin(cuentas_multi)].copy()
    resumen = (
        detalle.groupby("cuenta_bancaria")
        .agg(num_cedulas=("cedula", "nunique"), total_pagado=("monto", "sum"))
        .reset_index()
        .sort_values(["num_cedulas", "total_pagado"], ascending=[False, False])
    )
    # mismo empleado con varias cuentas (account hopping)
    hop = (
        nomina.groupby("cedula")["cuenta_bancaria"].nunique().reset_index(name="num_cuentas")
    )
    hop = hop[hop["num_cuentas"] > 1].sort_values("num_cuentas", ascending=False)
    return resumen, detalle, hop

def prueba_cuentas_no_autorizadas(nomina: pd.DataFrame, cuentas_aut: pd.DataFrame) -> pd.DataFrame:
    if cuentas_aut.empty:
        return pd.DataFrame()
    set_aut = set(str_clean(cuentas_aut["cuenta_bancaria"]))
    out = nomina[~nomina["cuenta_bancaria"].isin(set_aut)].copy()
    out["motivo"] = "Cuenta bancaria no autorizada"
    return out.sort_values(["fecha_pago", "cedula"])

def primera_cifra(n: float) -> int:
    n = abs(float(n))
    while n >= 10:
        n /= 10.0
    while 0 < n < 1:
        n *= 10.0
    return int(n) if n >= 1 else 0

def benford_analisis(montos: pd.Series) -> Tuple[pd.DataFrame, float, dict]:
    """Retorna tabla por dígito 1..9 con obs/exp y chi2."""
    montos = pd.to_numeric(montos, errors="coerce").fillna(0.0)
    montos = montos[montos > 0]
    if len(montos) == 0:
        return pd.DataFrame(), 0.0, {}
    obs = {d: 0 for d in range(1, 10)}
    for x in montos:
        d = primera_cifra(x)
        if d in obs:
            obs[d] += 1
    total = sum(obs.values())
    # Probabilidades Benford
    exp_p = {d: math.log10(1 + 1/d) for d in range(1, 10)}
    exp = {d: p * total for d, p in exp_p.items()}
    chi2 = sum(((obs[d] - exp[d]) ** 2) / exp[d] for d in range(1, 10) if exp[d] > 0)
    rows = []
    for d in range(1, 10):
        obs_c = obs[d]
        exp_c = exp[d]
        obs_pct = 100.0 * obs_c / total if total else 0.0
        exp_pct = 100.0 * exp_p[d]
        rows.append({
            "digito": d,
            "observado": obs_c,
            "esperado": round(exp_c, 2),
            "%_observado": round(obs_pct, 2),
            "%_benford": round(exp_pct, 2),
            "desv_pct": round(obs_pct - exp_pct, 2),
        })
    tabla = pd.DataFrame(rows)
    return tabla, chi2, exp_p

def prueba_asistencia(nomina: pd.DataFrame, asistencia: pd.DataFrame, min_dias: int = 1) -> pd.DataFrame:
    if asistencia.empty:
        return pd.DataFrame()
    tmp_n = nomina.copy()
    tmp_n["anio_mes"] = tmp_n["fecha_pago"].dt.to_period("M")
    tmp_a = asistencia.copy()
    tmp_a["anio_mes"] = tmp_a["fecha"].dt.to_period("M")
    # días asistidos por empleado/mes
    dias = (
        tmp_a.groupby(["cedula", "anio_mes"])["fecha"]
        .nunique()
        .reset_index(name="dias_asistidos")
    )
    merged = tmp_n.merge(dias, on=["cedula", "anio_mes"], how="left")
    merged["dias_asistidos"] = merged["dias_asistidos"].fillna(0).astype(int)
    out = merged[merged["dias_asistidos"] < int(min_dias)].copy()
    out["motivo"] = f"Asistencia insuficiente (<{min_dias} día(s) en el mes)"
    cols = ["fecha_pago", "cedula", "nombre", "monto", "cuenta_bancaria", "dias_asistidos", "motivo"]
    return out[cols].sort_values(["fecha_pago", "cedula"])

# ---------------------------
# Ejecutar pruebas
# ---------------------------
st.header("🧪 Resultados de las pruebas")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "1) Empleados fantasma",
    "2) Pagos post-baja",
    "3) Cuentas bancarias",
    "4) Benford (montos)",
    "5) Nómina vs Asistencia",
    "📦 Exportar resultados"
])

# 1) Fantasmas
with tab1:
    df_fantasmas = prueba_empleados_fantasma(df_nomina, df_empleados)
    st.metric("Registros fantasma detectados", len(df_fantasmas))
    st.dataframe(df_fantasmas, use_container_width=True)

# 2) Post-baja
with tab2:
    df_post_baja = prueba_pagos_post_baja(df_nomina, df_empleados)
    st.metric("Pagos posteriores a baja", len(df_post_baja))
    st.dataframe(df_post_baja, use_container_width=True)

# 3) Cuentas
with tab3:
    resumen_ctas, detalle_ctas, hop_ctas = prueba_cuentas_duplicadas(df_nomina)
    df_no_aut = prueba_cuentas_no_autorizadas(df_nomina, df_cuentas_aut)
    colA, colB, colC = st.columns(3)
    colA.metric("Cuentas compartidas", len(resumen_ctas))
    colB.metric("Registros en cuentas compartidas", len(detalle_ctas))
    colC.metric("Empleados con varias cuentas", len(hop_ctas))
    st.subheader("Resumen – Cuentas compartidas por varias cédulas")
    st.dataframe(resumen_ctas, use_container_width=True)
    st.subheader("Detalle – Pagos en cuentas compartidas")
    st.dataframe(detalle_ctas, use_container_width=True)
    st.subheader("Empleados con múltiples cuentas (account hopping)")
    st.dataframe(hop_ctas, use_container_width=True)
    if not df_no_aut.empty:
        st.subheader("⚠️ Cuentas NO autorizadas")
        st.dataframe(df_no_aut, use_container_width=True)

# 4) Benford
with tab4:
    if analizar_benford:
        tabla_benford, chi2, exp_p = benford_analisis(df_nomina["monto"])
        if not tabla_benford.empty:
            st.write("**Tabla por dígito (1..9):**")
            st.dataframe(tabla_benford, use_container_width=True)
            # Marcar desviaciones
            outliers = tabla_benford[tabla_benford["desv_pct"].abs() >= umbral_dev_pct]
            st.write(f"**Desviaciones ≥ {umbral_dev_pct}%:** {len(outliers)} dígitos")
            st.dataframe(outliers, use_container_width=True)
            # Chi-cuadrado y referencia crítica (df=8)
            st.info(f"Chi-cuadrado: **{chi2:.2f}** | Referencia crítica aproximada: 15.51 (α=0.05, df=8). "
                    "Valores por encima sugieren desviación significativa respecto a Benford.")
            # Gráfico
            chart_df = tabla_benford.melt(id_vars=["digito"], value_vars=["%_observado", "%_benford"],
                                          var_name="tipo", value_name="porcentaje")
            st.bar_chart(chart_df, x="digito", y="porcentaje", color="tipo", height=320, use_container_width=True)
        else:
            st.warning("No hay montos positivos suficientes para ejecutar Benford.")
    else:
        st.info("Activa la opción 'Incluir prueba de Benford' en la barra lateral.")
        
# 5) Nómina vs Asistencia
with tab5:
    if df_asistencia.empty:
        st.warning("No se cargó archivo de asistencia. Esta prueba es opcional pero recomendable.")
        df_asistencia_bad = pd.DataFrame()
    else:
        df_asistencia_bad = prueba_asistencia(df_nomina, df_asistencia, min_dias=min_dias_asistencia)
    st.metric("Registros con asistencia insuficiente", len(df_asistencia_bad))
    st.dataframe(df_asistencia_bad, use_container_width=True)

# 6) Exportar
with tab6:
    # Compilar todas las hojas
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_nomina.to_excel(writer, index=False, sheet_name="Nomina_Original")
        df_empleados.to_excel(writer, index=False, sheet_name="Empleados_Original")
        if not df_asistencia.empty:
            df_asistencia.to_excel(writer, index=False, sheet_name="Asistencia_Original")
        if not df_cuentas_aut.empty:
            df_cuentas_aut.to_excel(writer, index=False, sheet_name="Ctas_Autorizadas")
        # resultados
        prueba_sheets = [
            ("Empleados_Fantasmas", 'df_fantasmas'),
            ("Pagos_Post_Baja", 'df_post_baja'),
            ("Ctas_Compartidas", 'resumen_ctas'),
            ("Ctas_Compartidas_Detalle", 'detalle_ctas'),
            ("Empleados_Multicuentas", 'hop_ctas'),
            ("Ctas_No_Autorizadas", 'df_no_aut'),
            ("Asistencia_Insuficiente", 'df_asistencia_bad'),
            ("Benford_Detalle", 'tabla_benford' if analizar_benford else None),
        ]
        loc = locals()
        for sheet_name, varname in prueba_sheets:
            if varname and varname in loc:
                df_out = loc[varname]
                if isinstance(df_out, pd.DataFrame) and not df_out.empty:
                    df_out.to_excel(writer, index=False, sheet_name=sheet_name)
    st.download_button(
        label="⬇️ Descargar Excel con resultados",
        data=buffer.getvalue(),
        file_name="CAAT_Forense_Agroindu_Resultados.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.caption("© 2025 – CAAT Forense de nómina. Este dashboard es de apoyo y no reemplaza el juicio profesional ni la evidencia documental.")

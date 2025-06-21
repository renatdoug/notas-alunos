import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re

# Constantes
SCOPE = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
SHEET_NAME = "Boletins"
WORKSHEET_NOTAS = "Notas_Tabela"

# Funções auxiliares


def clean_nota_value(value):
    """Converte valores de nota, tratando vírgulas, datas e outros formatos."""
    if pd.isna(value):
        return 0.0
    value = str(value).strip()
    value = value.replace(',', '.')
    if re.match(r'^\d{1,2}/\d{1,2}$', value):
        try:
            parts = value.split('/')
            value = f"{parts[0]}.{parts[1]}"
        except:
            return 0.0
    value = re.sub(r'[^\d.]', '', value)
    parts = value.split('.')
    if len(parts) > 2:
        value = parts[0] + '.' + ''.join(parts[1:])
    return float(value) if value else 0.0


@st.cache_data(show_spinner=False, ttl=300)
def load_data(_client, sheet_name, worksheet_name):
    """Carrega dados da planilha."""
    try:
        sheet = _client.open(sheet_name).worksheet(worksheet_name)
        df = pd.DataFrame(sheet.get_all_records())
        if df.empty:
            st.error("Planilha vazia.")
            st.stop()
        required_cols = ['Série', 'Nome do Aluno', 'Matrícula',
                         'Bimestre', 'Componente Curricular', 'Tipo de Avaliação', 'Nota']
        if not all(col in df.columns for col in required_cols):
            st.error("Colunas obrigatórias ausentes na planilha.")
            st.stop()
        # Normalizar colunas de texto
        for col in required_cols[:-1]:  # Exceto 'Nota'
            df[col] = df[col].astype(str).str.strip().str.upper()
        df['Nota'] = df['Nota'].apply(clean_nota_value)
        return df
    except Exception as e:
        st.error(f"Erro ao acessar planilha: {e}")
        st.stop()


def validate_matricula(nome, matricula, alunos_serie):
    """Valida a matrícula do aluno."""
    return not alunos_serie[
        (alunos_serie['Nome do Aluno'].str.upper() == nome.upper()) &
        (alunos_serie['Matrícula'].astype(
            str).str.strip() == matricula.strip())
    ].empty


def calculate_media(resultado):
    """Calcula a média entre MENSAL e BIMESTRAL para cada componente curricular."""
    medias = {}
    mensal_rows = resultado[resultado['Tipo de Avaliação'] == 'MENSAL']
    bimestral_rows = resultado[resultado['Tipo de Avaliação'] == 'BIMESTRAL']

    for comp in resultado['Componente Curricular'].unique():
        mensal = mensal_rows[mensal_rows['Componente Curricular'] ==
                             comp]['Nota'].iloc[0] if not mensal_rows[mensal_rows['Componente Curricular'] == comp].empty else 0.0
        bimestral = bimestral_rows[bimestral_rows['Componente Curricular'] ==
                                   comp]['Nota'].iloc[0] if not bimestral_rows[bimestral_rows['Componente Curricular'] == comp].empty else 0.0
        if mensal > 0.0 or bimestral > 0.0:
            medias[comp] = (mensal + bimestral) / 2
        else:
            medias[comp] = 0.0
    return medias


def check_recuperacao(medias):
    """Verifica se recuperação é necessária para médias < 7."""
    recuperacao_needed = []
    for comp, media in medias.items():
        if media < 7:
            recuperacao_needed.append(f"{comp} (Média: {media:.2f})")
    return recuperacao_needed


def display_boletim(resultado):
    """Exibe o boletim com estilização, cálculo de média e mensagem de recuperação."""
    # Definir ordem desejada das colunas
    desired_order = ['MENSAL', 'BIMESTRAL',
                     'MEDIA', 'RECUPERAÇÃO', 'RECUPERAÇÃO FINAL']
    # Filtrar tipos de avaliação presentes
    available_types = resultado['Tipo de Avaliação'].unique()
    ordered_types = [t for t in desired_order if t in available_types]

    boletim = (
        resultado.pivot_table(
            index='Componente Curricular',
            columns='Tipo de Avaliação',
            values='Nota',
            aggfunc='first'
        )
        .reindex(columns=ordered_types)
        .reset_index()
    )
    boletim.columns.name = None
    boletim = boletim.rename(columns={
        "MENSAL": "Men",
        "BIMESTRAL": "Bim",
        "MEDIA": "Med",
        "RECUPERAÇÃO": "Rec",
        "RECUPERAÇÃO FINAL": "Rec Final"
    })

    # Calcular médias
    medias = calculate_media(resultado)
    # Adicionar coluna de média calculada
    boletim['Med'] = [medias.get(comp, 0.0)
                      for comp in boletim['Componente Curricular']]

    def colorir_nota(val):
             if isinstance(val, (int, float)):
                      if val < 7:
                               return 'background-color: #ffd6d6; color: black; font-weight: bold; text-align: center'  # tom de vermelho claro
                      else:
                               return 'background-color: #d6ecff; color: black; font-weight: bold; text-align: center'  # tom de azul claro
             return ''


    st.success("Notas encontradas:")
    st.dataframe(
        boletim.style
        .applymap(colorir_nota, subset=boletim.columns[1:])
        .format("{:.2f}", subset=boletim.columns[1:], na_rep="-")
    )

    # Verificar e exibir mensagem de recuperação por disciplina
    recuperacao_needed = check_recuperacao(medias)
    if recuperacao_needed:
        st.warning("Recuperação necessária para: " +
                   ", ".join(recuperacao_needed))

    # Verificar e exibir lista de disciplinas com média < 7
    componentes_recuperacao = [comp for comp,
                               media in medias.items() if media < 7]
    if componentes_recuperacao:
        st.warning("O ALUNO DEVERÁ FAZER PROVA DE RECUPERAÇÃO NA(S) SEGUINTE(S) DISCIPLINA(S): " +
                   ", ".join(componentes_recuperacao))


# Autenticação via st.secrets
try:
    creds_dict = dict(st.secrets["google_credentials"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
    client = gspread.authorize(creds)
except Exception as e:
    st.error(f"Erro ao autenticar com Google Sheets: {e}")
    st.stop()

# Carregar dados
df = load_data(client, SHEET_NAME, WORKSHEET_NOTAS)

# Título
st.title("Consulta de Notas - Filtragem por Turma e Segurança")

# Botão de nova consulta
if "consultado" in st.session_state and st.button("Nova consulta"):
    st.session_state.clear()
    st.rerun()

# 1️⃣ Selecionar Série
series = sorted(df["Série"].dropna().unique().tolist())
serie_selecionada = st.selectbox(
    "Selecione a série:", [""] + series, key="serie")

# 2️⃣ Selecionar Aluno
nome_selecionado = ""
matricula_input = ""
bimestres = []
if serie_selecionada:
    alunos_serie = df[df["Série"] == serie_selecionada][[
        "Nome do Aluno", "Matrícula"]].drop_duplicates()
    nomes = sorted(alunos_serie["Nome do Aluno"].tolist())
    nome_selecionado = st.selectbox(
        "Selecione o aluno:", [""] + nomes, key="nome")

    # 3️⃣ Selecionar Bimestre
    if nome_selecionado:
        bimestres = sorted(df[df["Nome do Aluno"] == nome_selecionado]
                           ["Bimestre"].dropna().unique().tolist())
        bimestre = st.selectbox(
            "Selecione o bimestre/período:", [""] + bimestres + ["Final"], key="bimestre")

        # 4️⃣ Digitar matrícula
        matricula_input = st.text_input(
            "Digite a matrícula do aluno", type="password", key="matricula")

        # 5️⃣ Botão para consultar
        if st.button("Consultar"):
            if validate_matricula(nome_selecionado, matricula_input, alunos_serie):
                resultado = df[
                    (df['Nome do Aluno'].str.upper() == nome_selecionado.upper()) &
                    (df['Matrícula'].astype(str).str.strip() == matricula_input.strip()) &
                    (df['Série'] == serie_selecionada) &
                    (df['Bimestre'] == bimestre)
                ]
                if not resultado.empty:
                    display_boletim(resultado)
                    st.session_state["consultado"] = True
                    # Botão de download
                    csv = resultado.to_csv(index=False)
                    st.download_button("Baixar Boletim", csv,
                                       "boletim.csv", "text/csv")
                else:
                    st.warning(
                        "Nenhuma nota lançada para esse bimestre/período.")
            else:
                st.error("Matrícula incorreta para o aluno selecionado.")

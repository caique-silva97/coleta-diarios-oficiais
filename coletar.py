import argparse
import requests
import time
import hashlib
import pymupdf
from datetime import date, datetime, timedelta
from urllib.parse import quote
from pathlib import Path

URL_BUSCA = "https://diariooficial.fortaleza.ce.gov.br/api/search"
WAIT = 6 #segundos; a fonte pede 5 (captcha-required -> intervalSeconds)
URL_PDF_FORTALEZA = "https://diariooficial.fortaleza.ce.gov.br/api/nodes/{id}/content?inline=1&name={nome}"
PASTA_PDF = Path("pdfs")


def tipo_fortaleza(nr):
    nr = nr.replace(" ", "").lower()
    if nr.endswith("s") and nr[:-1].isdigit():
        return "suplemento", nr[:-1]
    if nr.isdigit():
        return "normal", nr
    return None, nr


def item_fortaleza(entry):
    tipo, numero = tipo_fortaleza(entry["nrDiarioOficial"])
    return {
        "fonte": "fortaleza",
        "data_publicacao": entry["dataPublicacao"][:10],
        "numero": numero,
        "tipo": tipo,
        "url": URL_PDF_FORTALEZA.format(id=entry["id"], nome=quote(entry["name"])),
        "titulo_fonte": entry["name"],
    }


def baixar_pdf(url):
    nome = hashlib.sha256(url.encode()).hexdigest()[:16] + ".pdf"
    caminho = PASTA_PDF / nome
    if not caminho.exists():
        resposta = requests.get(url, timeout=60)
        resposta.raise_for_status()
        if not resposta.content.startswith(b"%PDF"):
            raise ValueError(f"A resposta não é um PDF: {url}")
        PASTA_PDF.mkdir(exist_ok=True)
        caminho.write_bytes(resposta.content)
        time.sleep(WAIT)
    conteudo = caminho.read_bytes()
    return caminho, hashlib.sha256(conteudo).hexdigest()


def extrair_texto(caminho):
    with pymupdf.open(caminho) as doc:
        paginas = [pagina.get_text() for pagina in doc]
    return "\f".join(paginas), len(paginas)


def primeiro_dia_mes_seguinte(dia):
    return (dia.replace(day=28) + timedelta(days=4)).replace(day=1)


def meses_da_coleta(inicio, fim):
    atual = (inicio.replace(day=1) - timedelta(days=1)).replace(day=1) #1º dia do mês anterior
    ultimo = primeiro_dia_mes_seguinte(fim)
    meses = []
    while atual <= ultimo:
        meses.append((atual.year, atual.month))
        atual = primeiro_dia_mes_seguinte(atual)
    return meses


def listar_fortaleza(inicio, fim):
    inventario = []
    totais = {}
    for ano, mes in meses_da_coleta(inicio, fim):
        entradas, total = buscar_mes_fortaleza(ano, mes)
        totais[f"{ano}-{mes:02d}"] = total
        for entry in entradas:
            item = item_fortaleza(entry)
            data = date.fromisoformat(item["data_publicacao"])
            item["destino"] = None if inicio <= data <= fim else "fora_do_intervalo"
            inventario.append(item)
    return inventario, totais


def processar(inventario):
    edicoes = []
    vistos = {}
    for item in inventario:
        if item["destino"] == "fora_do_intervalo":
            continue
        try:
            caminho, sha = baixar_pdf(item["url"])
            texto, paginas = extrair_texto(caminho)
        except Exception as erro:
            item["destino"], item["motivo"] = "falha", str(erro)
            continue
        chave = (item["destino"], item["numero"], item["tipo"], sha)
        if chave in vistos:
            item["destino"], item["motivo"] = "duplicata", f"conteúdo idêntico a {vistos[chave]}"
            continue
        vistos[chave] = item["url"]
        item["destino"] = "coletado"
        edicoes.append({
            "fonte": item["fonte"], "data_publicacao": item["data_publicacao"],
            "numero": item["numero"], "tipo": item["tipo"], "url": item["url"],
            "titulo_fonte": item["titulo_fonte"], "sha256": sha, "paginas": paginas,
            "texto": texto, "coletado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
    return edicoes


def ler_argumentos():
    parser = argparse.ArgumentParser(description= "Coleta diários oficiais de Macapá e Fortaleza.")
    parser.add_argument("--inicio", required=True, type=date.fromisoformat, help="data inicial, AAAA-MM-DD")
    parser.add_argument("--fim", required=True, type=date.fromisoformat, help="data final, AAAA-MM-DD")
    return parser.parse_args()

def buscar_mes_fortaleza(ano, mes):
    entradas = []
    pagina = 1
    while True:  
        payload = {"ano": str(ano), "mes": f"{mes:02d}", "nrDom": None, "conteudo": None, "captcha": "", "page": pagina, "pageSize": 30}
        resposta = requests.post(URL_BUSCA, json=payload, timeout=30)
        resposta.raise_for_status()
        lista = resposta.json()["list"]
        entradas += [item["entry"] for item in lista["entries"]]
        time.sleep(WAIT)
        if not lista["pagination"]["hasMoreItems"]:
            return entradas, lista["pagination"]["totalItems"]
        pagina += 1


if __name__ == "__main__":
    args = ler_argumentos()
    inventario, totais = listar_fortaleza(args.inicio, args.fim)
    edicoes = processar(inventario)
    for item in inventario:
        if item["destino"] != "fora_do_intervalo":
            print(item["numero"], item["tipo"], item["destino"], item.get("motivo", ""))
    print(len(edicoes), "edições coletadas")
    primeiro = min(edicoes, key=lambda e: e["data_publicacao"])
    ultimo = max(edicoes, key=lambda e: e["data_publicacao"])
    print("primeiro:", primeiro["numero"], primeiro["data_publicacao"])
    print("ultimo:", ultimo["numero"], ultimo["data_publicacao"])

    

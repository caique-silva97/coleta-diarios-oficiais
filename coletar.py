import argparse
import requests
import time
import hashlib
import pymupdf
import json
import html
import re
import subprocess
from datetime import date, datetime, timedelta
from urllib.parse import quote
from pathlib import Path
from collections import Counter

#fortaleza const
URL_BUSCA = "https://diariooficial.fortaleza.ce.gov.br/api/search"
WAIT = 6 #segundos; a fonte pede 5 (captcha-required -> intervalSeconds)
URL_PDF_FORTALEZA = "https://diariooficial.fortaleza.ce.gov.br/api/nodes/{id}/content?inline=1&name={nome}"
PASTA_PDF = Path("pdfs")

#macapa
URL_MACAPA = "https://macapa.ap.gov.br/diarios-oficiais/"
URL_LIVEWIRE = "https://macapa.ap.gov.br/livewire/update"
SESSAO = requests.Session() 

LIMITE_LEGIVEL = 0.15 # calibrado calibrado em 27/11: texto bom >= 0,20; lixo de OCR <= 0,11

def requisitar(metodo, url, **kwargs):
    for tentativa in (1, 2):
        try:
            resposta = requests.request(metodo, url, timeout=60, **kwargs)
            resposta.raise_for_status()
            return resposta
        except requests.RequestException:
            if tentativa == 2:
                raise
            time.sleep(WAIT)


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
        resposta = requisitar("GET", url)
        if not resposta.content.startswith(b"%PDF"):
            raise ValueError(f"A resposta não é um PDF: {url}")
        PASTA_PDF.mkdir(exist_ok=True)
        caminho.write_bytes(resposta.content)
        time.sleep(WAIT)
    conteudo = caminho.read_bytes()
    return caminho, hashlib.sha256(conteudo).hexdigest()


def extrair_texto(caminho):
    cache = caminho.with_suffix(".txt")
    if cache.exists():
        texto = cache.read_text(encoding="utf-8")
        return texto, texto.count("\f") + 1
    with pymupdf.open(caminho) as doc:
        paginas = []
        for pagina in doc:
            texto = pagina.get_text()
            if len(texto.strip()) < 50:
                texto = ocr_pagina(pagina)
            paginas.append(texto)
    texto = "\f".join(paginas)
    cache.write_text(texto, encoding="utf-8")
    return texto, len(paginas)
    

PALAVRAS_COMUNS = {"de", "a", "o", "que", "e", "do", "da", "em", "um", "para", "com", "não",
                   "uma", "os", "no", "se", "na", "por", "as", "dos", "ao", "das", "à", "nos",
                   "ou", "sua", "seu", "pela", "pelo", "art"}


def legibilidade(texto):
    palavras = re.findall(r"[a-zà-ú]+", texto.lower())
    if not palavras:
        return 0.0
    return sum(p in PALAVRAS_COMUNS for p in palavras) / len(palavras)


def ocr(pagina):
    imagem = pagina.get_pixmap(dpi=300).tobytes("png")
    resultado = subprocess.run(["tesseract", "stdin", "stdout", "-l", "por"],
                               input=imagem, capture_output=True, check=True)
    return resultado.stdout.decode("utf-8")


def ocr_pagina(pagina):
    texto= ocr(pagina)
    if legibilidade(texto) >= LIMITE_LEGIVEL:
        return texto
    for giro in (90, 270, 180):
        pagina.set_rotation(giro)
        girado = ocr(pagina)
        if legibilidade(girado) >= LIMITE_LEGIVEL:
            return girado
    return texto


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


def abrir_macapa():
    pagina = requisitar("GET", URL_MACAPA).text
    token = re.search(r'data-csrf="([^"]+)"', pagina).group(1)
    snapshot = html.unescape(re.search(r'wire:snapshot="([^"]+)"', pagina).group(1))
    time.sleep(WAIT)
    return token, snapshot


def chamar_livewire(token, snapshot, metodo, parametro):
    corpo = {"_token": token, "components": [{"snapshot": snapshot, "updates": {},
             "calls":[{"path": "", "method": metodo, "params": [parametro]}]}]}
    resposta = requisitar("POST", URL_LIVEWIRE, json=corpo, headers={"X-Livewire": ""})
    time.sleep(WAIT)
    return resposta.json()["components"][0]["snapshot"]


def buscar_mes_macapa(token, snapshot, ano, mes):
    snapshot = chamar_livewire(token, snapshot, "changeYear", str(ano))
    snapshot = chamar_livewire(token, snapshot, "setMonth", f"{mes:02d}")
    dados = json.loads(snapshot)["data"]
    itens = [par[0] for par in dados["tabDiaries"][0]]
    return itens, snapshot


def item_macapa(item):
    achado = re.fullmatch(r"DIÁRIO OFICIAL Nº: \d+(-A)?-\d{2}/\d{2}/\d{4}", item["title"])
    if achado is None:
        tipo = None
    elif achado.group(1):
        tipo = "suplemento"
    else:
        tipo = "normal"
    dia, mes, ano = item["date"].split("/")
    return {
        "fonte": "macapa",
        "data_publicacao": f"{ano}-{mes}-{dia}",
        "numero": item["id"],
        "tipo": tipo,
        "url": item["link"],
        "titulo_fonte": item["title"],
    }


def listar_macapa(inicio, fim):
    token, snapshot = abrir_macapa()
    inventario = []
    for ano, mes in meses_da_coleta(inicio, fim):
        itens, snapshot = buscar_mes_macapa(token, snapshot, ano, mes)
        for bruto in itens:
            item = item_macapa(bruto)
            data = date.fromisoformat(item["data_publicacao"])
            item["destino"] = None if inicio <= data <= fim else "fora_do_intervalo"
            inventario.append(item)
    return inventario


def processar(inventario):
    edicoes = []
    vistos = {}
    for item in inventario:
        if item["destino"] == "fora_do_intervalo":
            continue
        print(item["fonte"], item["numero"], item["tipo"], flush=True)
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


def gravar_jsonl(caminho, registros):
    with open(caminho, "w", encoding="utf-8") as arquivo:
        for registro in registros:
            arquivo.write(json.dumps(registro, ensure_ascii=False)+ "\n")


def gravar(edicoes, inventario, totais, inicio, fim):
    pasta = Path("dados")
    pasta.mkdir(exist_ok=True)
    gravar_jsonl(pasta / "edicoes.jsonl", edicoes)
    gravar_jsonl(pasta / "inventario.jsonl", inventario)
    resumo = {
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "executado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "totais_fonte": {"fortaleza": totais},
    }
    (pasta / "coleta.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")


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
        resposta = requisitar("POST", URL_BUSCA, json=payload)
        lista = resposta.json()["list"]
        entradas += [item["entry"] for item in lista["entries"]]
        time.sleep(WAIT)
        if not lista["pagination"]["hasMoreItems"]:
            return entradas, lista["pagination"]["totalItems"]
        pagina += 1


if __name__ == "__main__":
    args = ler_argumentos()
    inventario_fortaleza, totais = listar_fortaleza(args.inicio, args.fim)
    inventario_macapa = listar_macapa(args.inicio, args.fim)
    inventario = inventario_fortaleza + inventario_macapa
    edicoes = processar(inventario)
    gravar(edicoes, inventario, totais, args.inicio, args.fim)
    print(Counter((i["fonte"], i["destino"]) for i in inventario))
    for e in edicoes:
        por_pagina = [len(p.strip()) for p in e["texto"].split("\f")]
        print(e["fonte"], e["numero"], e["tipo"], e["paginas"], "páginas | caracteres:", por_pagina[:10])
    
    

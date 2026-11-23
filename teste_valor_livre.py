"""Teste local do valor livre no site (Playwright). Leitura real do Supabase; so o campo valor_livre das 2 primeiras
cotas e alterado na resposta (em memoria). O cota-pagar e interceptado: nada e cobrado."""
import json, os, re, subprocess, sys, threading, http.server, functools
from playwright.sync_api import sync_playwright

AQUI = os.path.dirname(os.path.abspath(__file__))
CAP = os.path.abspath(os.path.join(AQUI, "..", "casamento-ana-matheus", "capturas"))
os.makedirs(CAP, exist_ok=True)

h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=AQUI)
h.log_message = lambda *a, **k: None
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/index.html" % srv.server_port

falhas, erros = [], []
def ok(c, m):
    print(("OK   " if c else "FALHA ") + m)
    if not c: falhas.append(m)

def valor54(payload):
    m = re.search(r"54(\d{2})(\d+\.\d{2})", payload)
    return m.group(2) if m else None

def mexer(route):
    r = route.fetch()
    try:
        d = r.json()
    except Exception:
        return route.fulfill(response=r)
    if isinstance(d, list) and d and "valor" in d[0]:
        d[0]["valor_livre"] = True
        d[0]["valor_minimo"] = 20
        d[1]["valor_livre"] = True
        d[1]["valor_minimo"] = None
    route.fulfill(response=r, body=json.dumps(d), headers={**r.headers, "content-type": "application/json"})

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 402, "height": 900}, permissions=["clipboard-read", "clipboard-write"])
    pg = ctx.new_page()
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.route("**/rest/v1/presentes*", mexer)
    posts = []
    def pagar(route):
        posts.append(json.loads(route.request.post_data))
        route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"},
                      body=json.dumps({"link": "https://example.invalid/pagar"}))
    pg.route("**/functions/v1/cota-pagar", pagar)
    manual = {"on": False}
    def cfgmexer(route):
        r = route.fetch()
        if not manual["on"]:
            return route.fulfill(response=r)
        d = r.json()
        d = [x for x in d if x["chave"] not in ("pix", "pagamento")]
        d.append({"chave": "pix", "valor": {"chave": "teste@exemplo.com", "nome": "Casal Teste", "cidade": "Palmas", "mensagem": ""}})
        d.append({"chave": "pagamento", "valor": {"online": False}})
        route.fulfill(response=r, body=json.dumps(d), headers={**r.headers, "content-type": "application/json"})
    pg.route("**/rest/v1/config*", cfgmexer)
    pg.route("https://example.invalid/**", lambda r: r.fulfill(status=200, body="fim"))

    # ---- modo online (teste_pagamento=1)
    pg.goto(URL + "?teste_pagamento=1")
    pg.wait_for_selector("#cotas .cota")
    cards = pg.locator("#cotas .cota")
    t0, t1, t2 = [cards.nth(i).inner_text().replace("\u00a0", " ") for i in range(3)]
    ok("a partir de R$ 20,00" in t0 and "valor livre" in t0.lower(), "card 1 mostra 'a partir de R$ 20,00' + valor livre")
    ok("a partir de R$ 10,00" in t1, "card 2 (sem minimo) mostra 'a partir de R$ 10,00'")
    ok("a partir de" not in t2 and "valor livre" not in t2.lower(), "card 3 (sem valor livre) fica como hoje")
    pg.locator("#cotas").scroll_into_view_if_needed()
    pg.screenshot(path=os.path.join(CAP, "valor-livre-site-cards.png"), clip=None)
    cards.nth(0).click()
    pg.wait_for_selector("#cota-janela[open]")
    ok(pg.is_visible("#cj-livre"), "janela mostra o seletor de valor")
    ok(pg.input_value("#vl-input") == "250", "pre-preenchido com o valor do presente (250)")
    ok("R$" in pg.inner_text("#cj-preco-pix"), "preco do Pix visivel")
    p1 = pg.inner_text("#cj-preco-pix")
    pg.click("#vl-mais")
    ok(pg.input_value("#vl-input") == "260" and pg.inner_text("#cj-preco-pix") != p1, "+ soma 10 e atualiza o preco")
    pg.click("#vl-menos"); pg.click("#vl-menos")
    ok(pg.input_value("#vl-input") == "240", "- subtrai 10")
    pg.fill("#vl-input", "5")
    ok(pg.is_visible("#vl-erro") and "mínimo" in pg.inner_text("#vl-erro"), "abaixo do minimo mostra erro")
    ok(pg.locator("button.pagar").first.is_disabled(), "botoes de pagar desligados com valor invalido")
    pg.fill("#vl-input", "12,345")
    ok(pg.locator("button.pagar").first.is_disabled(), "tres casas decimais recusadas")
    pg.click("#vl-sug button >> nth=2")
    sel = pg.locator("#vl-sug button.on").count()
    ok(sel == 1, "sugestao rapida seleciona o valor")
    pg.fill("#vl-input", "73,50")
    ok("73,50" in pg.inner_text("#cj-valor"), "titulo da janela acompanha o valor")
    pg.fill("#cj-pagar [name=nome]", "Fulano de Tal")
    pg.screenshot(path=os.path.join(CAP, "valor-livre-site-janela-online.png"))
    pg.click("button.pagar[data-metodo=pix]")
    pg.wait_for_timeout(800)
    ok(len(posts) == 1 and posts[0].get("valor") == 73.5, "POST envia valor 73.5 -> %s" % (posts[0] if posts else None))
    # presente sem valor livre: nao envia valor
    pg.goto(URL + "?teste_pagamento=1"); pg.wait_for_selector("#cotas .cota")
    pg.locator("#cotas .cota").nth(2).click()
    ok(not pg.is_visible("#cj-livre"), "presente sem valor livre: sem seletor")
    pg.fill("#cj-pagar [name=nome]", "Fulano de Tal")
    pg.click("button.pagar[data-metodo=pix]"); pg.wait_for_timeout(800)
    ok(len(posts) == 2 and "valor" not in posts[1], "presente sem valor livre: POST sem valor")

    # ---- modo Pix manual (sem online)
    manual["on"] = True
    pg.goto(URL); pg.wait_for_selector("#cotas .cota")
    if pg.locator("#cotas .cota:not([disabled])").count():
        pg.locator("#cotas .cota").nth(0).click()
        pg.wait_for_selector("#cota-janela[open]")
        pg.wait_for_selector("#cj-qr svg", timeout=10000)
        pg.click("#cj-copiar"); a = pg.evaluate("navigator.clipboard.readText()")
        ok(valor54(a) == "250.00", "Pix copia-e-cola inicial com 250.00 (%s)" % valor54(a))
        pg.fill("#vl-input", "88,80"); pg.wait_for_timeout(500)
        pg.click("#cj-copiar"); a2 = pg.evaluate("navigator.clipboard.readText()")
        ok(valor54(a2) == "88.80", "Pix atualiza para 88.80 (%s)" % valor54(a2))
        pg.fill("#vl-input", "1"); ok(pg.is_disabled("#cj-copiar"), "valor invalido desliga o copiar")
        pg.fill("#vl-input", "88,80")
        pg.screenshot(path=os.path.join(CAP, "valor-livre-site-janela-pix.png"))
    else:
        print("AVISO: Pix manual nao liberado (sem chave); modo manual nao testado")

    # celular estreito
    pg.set_viewport_size({"width": 360, "height": 740})
    ok(pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "sem rolagem horizontal em 360px")
    b.close()

srv.shutdown()
erros = [e for e in erros if "fonts" not in e and "example.invalid" not in e and "ERR_FAILED" not in e]
ok(not erros, "console sem erros %s" % erros[:3])
sys.exit(1 if falhas else 0)

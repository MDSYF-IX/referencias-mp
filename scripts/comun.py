# Funciones compartidas por la carga desde datos abiertos (carga.py) y la actualización
# diaria desde la API (diaria.py): filtros, campos de cada licitación y archivos publicados.
import json, os, re, unicodedata, urllib.request, time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(RAIZ, 'config')
FILTROS = json.load(open(os.path.join(CONFIG, 'filtros.json'), encoding='utf-8'))
TIPOLOGIAS = json.load(open(os.path.join(CONFIG, 'tipologias.json'), encoding='utf-8'))

# Columnas del formato compacto: {"campos": CAMPOS, "filas": [[...], ...]}.
CAMPOS = ['cod', 'nom', 'org', 'reg', 'com', 'tipo', 'fpub', 'fadj', 'mon', 'est', 'adj', 'adj_uf', 'ofe', 'prov', 'tipol', 'bip', 'obs',
          'estado', 'fcie', 'est_uf']


def estado_norm(txt):
    """Estado de Mercado Público → 'adjudicada' | 'cerrada' (en evaluación) | 'publicada' | None.
    Desiertas, revocadas y suspendidas no se incluyen."""
    n = str(txt or '').strip().lower()
    for e in ('adjudicada', 'cerrada', 'publicada'):
        if n.startswith(e):
            return e
    return None


def es_adjudicada(x):
    return (x.get('estado') or 'adjudicada') == 'adjudicada'


def norm(s):
    """Minúsculas, sin tildes y sin dobles espacios."""
    s = unicodedata.normalize('NFD', str(s or '').lower()).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', s).strip()


# Las 16 regiones: slug del archivo y nombre. Se reconocen por una parte del nombre normalizado.
REGIONES = [
    ('arica', 'Arica y Parinacota', 'arica'), ('tarapaca', 'Tarapacá', 'tarapaca'), ('antofagasta', 'Antofagasta', 'antofagasta'),
    ('atacama', 'Atacama', 'atacama'), ('coquimbo', 'Coquimbo', 'coquimbo'), ('valparaiso', 'Valparaíso', 'valparaiso'),
    ('metropolitana', 'Metropolitana de Santiago', 'metropolitana'), ('ohiggins', "Libertador General Bernardo O'Higgins", 'higgins'),
    ('maule', 'Maule', 'maule'), ('nuble', 'Ñuble', 'nuble'), ('biobio', 'Biobío', 'biobio'), ('araucania', 'La Araucanía', 'araucan'),
    ('losrios', 'Los Ríos', 'los rios'), ('loslagos', 'Los Lagos', 'los lagos'), ('aysen', 'Aysén', 'aysen'), ('magallanes', 'Magallanes', 'magallanes'),
]


def region_slug(txt):
    n = norm(txt).replace('-', ' ')
    for slug, _, clave in REGIONES:
        if clave in n:
            return slug
    return None


def tipo_de_codigo(cod):
    """El tipo va al final del código: 1234-56-LR26 → LR."""
    m = re.search(r'-([A-Z][A-Z0-9])\d{2}$', str(cod or '').strip())
    return m.group(1) if m else None


def _tiene(palabras, n):
    return any(re.search(r'\b' + re.escape(p), n) for p in palabras)


def es_obra(tipo, nombre, bandera_obras):
    """Regla de inclusión (config/filtros.json):
    - nunca si el nombre tiene una palabra de «palabras_no_obras» (ej. adquisición);
    - O1/O2 siempre;
    - LR/I2: bandera Obras = 2, o palabras de obras sin palabras de diseño/servicio/estudio."""
    if tipo not in FILTROS['tipos']:
        return False
    n = norm(nombre)
    if _tiene(FILTROS['palabras_no_obras'], n):
        return False
    if tipo in FILTROS['tipos_siempre_obras']:
        return True
    if str(bandera_obras) == '2':
        return True
    return _tiene(FILTROS['palabras_obras'], n) and not _tiene(FILTROS['palabras_excluir_si_solo_palabras'], n)


def tipologia(nombre):
    n = norm(nombre)
    for t, pals in TIPOLOGIAS.items():
        if _tiene(pals, n):
            return t
    return 'otros'


def codigo_bip(*textos):
    for t in textos:
        m = re.search(r'\b(\d{8}-[\dkK])\b', str(t or ''))
        if m:
            return m.group(1).upper()
    return None


def num(s):
    """'2,16e+09' / '611330260' / 'NA' → float."""
    s = str(s or '').strip()
    if not s or s.upper() == 'NA':
        return 0.0
    try:
        return float(s.replace(',', '.'))
    except ValueError:
        return 0.0


def get_json(url, intentos=4, pausa=0.4):
    """GET con reintentos ante 5xx o timeout (1, 2, 4, 8 s) y ante 429, límite de consultas
    por segundo de la API (5, 10, 20, 40 s)."""
    for k in range(intentos + 1):
        espera = 2 ** k
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'referencias-mp'}), timeout=60) as r:
                time.sleep(pausa)
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or k == intentos:
                raise
            if e.code == 429:
                espera = 5 * 2 ** k
        except (urllib.error.URLError, TimeoutError):
            if k == intentos:
                raise
        time.sleep(espera)


# ── UF diaria (mindicador.cl, por año) ─────────────────────────────────────────────
def cargar_uf(publico, anios):
    ruta = os.path.join(publico, 'mp', 'uf.json')
    uf = json.load(open(ruta, encoding='utf-8')) if os.path.exists(ruta) else {}
    cmf = os.environ.get('CMF_API_KEY')
    for a in sorted(set(anios)):
        if any(k.startswith(f'{a}-') for k in uf) and a < time.localtime().tm_year:
            continue
        try:
            for x in get_json(f'https://mindicador.cl/api/uf/{a}').get('serie', []):
                uf[x['fecha'][:10]] = x['valor']
        except Exception as e:
            print('UF', a, 'mindicador.cl no disponible:', e)
            if not cmf:
                continue
            # Respaldo: API de la CMF ({"UFs":[{"Valor":"38.416,69","Fecha":"2025-01-01"}]}).
            try:
                for x in get_json(f'https://api.cmfchile.cl/api-sbifv3/recursos_api/uf/{a}?apikey={cmf}&formato=json').get('UFs', []):
                    uf[x['Fecha'][:10]] = float(x['Valor'].replace('.', '').replace(',', '.'))
            except Exception as e2:
                print('UF', a, 'CMF no disponible:', e2)
    uf = dict(sorted(uf.items()))
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    json.dump(uf, open(ruta, 'w', encoding='utf-8'), separators=(',', ':'))
    return uf


def uf_de(uf, fecha):
    """UF del día; si falta (fin de semana sin dato), la del último día anterior con valor."""
    if not fecha:
        return None
    if fecha in uf:
        return uf[fecha]
    prev = [k for k in uf if k <= fecha]
    return uf[max(prev)] if prev else None


def completar(L, uf):
    """Campos calculados: adj_uf, est_uf, tipología, BIP y observación de montos no confiables.
    En proceso (sin adjudicar) solo hay presupuesto estimado: est_uf con la UF de la publicación."""
    L['est_uf'] = monto_uf(L.get('est'), L['mon'], uf_de(uf, L.get('fpub')))
    if not es_adjudicada(L):
        L.update(adj=None, adj_uf=None, fadj=None, prov=[])
        L['tipol'] = tipologia(L['nom'])
        L['bip'] = L.get('bip') or codigo_bip(L['nom'], L.pop('desc', ''))
        L.pop('desc', None)
        L['obs'] = None
        return L
    v = uf_de(uf, L.get('fadj') or L.get('fpub'))
    obs = []
    if L['mon'] == 'CLF':
        L['adj_uf'] = round(L['adj'], 2)
    elif L['mon'] == 'CLP' and v:
        L['adj_uf'] = round(L['adj'] / v, 2)
        if L['adj'] < FILTROS['monto_minimo_clp']:
            obs.append('monto adjudicado muy bajo para una obra: revisar la ficha')
    else:
        L['adj_uf'] = None
    if not L['adj']:
        obs.append('sin monto adjudicado')
    L['tipol'] = tipologia(L['nom'])
    # La API trae CodigoBIP; los datos abiertos no: se busca en el nombre y la descripción.
    L['bip'] = L.get('bip') or codigo_bip(L['nom'], L.pop('desc', ''))
    L.pop('desc', None)
    L['obs'] = '; '.join(obs) or None
    return L


# ── Archivos publicados: mp/<region>/<año>.json e indice.json ───────────────────────
def leer_region(publico, reg):
    """Todas las licitaciones publicadas de la región: {cod: dict}."""
    carpeta = os.path.join(publico, 'mp', reg)
    out = {}
    if os.path.isdir(carpeta):
        for f in os.listdir(carpeta):
            if f.endswith('.json'):
                d = json.load(open(os.path.join(carpeta, f), encoding='utf-8'))
                for fila in d['filas']:
                    x = dict(zip(d['campos'], fila))
                    out[x['cod']] = x
    return out


def monto_uf(monto, mon, v):
    if not monto:
        return None
    if mon == 'CLF':
        return round(monto, 2)
    return round(monto / v, 2) if mon == 'CLP' and v else None


def combinar(viejo, nuevo):
    """Una adjudicada no vuelve a «en proceso»: los archivos de datos abiertos de meses pasados
    pueden traer un estado antiguo («Cerrada») de una licitación que la API ya trae adjudicada."""
    if viejo and es_adjudicada(viejo) and not es_adjudicada(nuevo):
        return viejo
    return nuevo


def rellenar_uf(lics, uf):
    """Completa adj_uf y est_uf de las filas que quedaron sin UF (la fuente no respondió)."""
    for x in lics.values():
        if x.get('est_uf') is None and x.get('est'):
            x['est_uf'] = monto_uf(x['est'], x['mon'], uf_de(uf, x['fpub']))
        if x.get('adj_uf') is None and x.get('adj') and x['mon'] in ('CLP', 'CLF'):
            v = uf_de(uf, x.get('fadj') or x['fpub'])
            if x['mon'] == 'CLF':
                x['adj_uf'] = round(x['adj'], 2)
            elif v:
                x['adj_uf'] = round(x['adj'] / v, 2)


def escribir_region(publico, reg, lics):
    """Un archivo por año de adjudicación (o de publicación si aún no tiene fecha)."""
    carpeta = os.path.join(publico, 'mp', reg)
    os.makedirs(carpeta, exist_ok=True)
    por_anio = {}
    for x in lics.values():
        por_anio.setdefault((x.get('fadj') or x['fpub'])[:4], []).append(x)
    for f in os.listdir(carpeta):
        if f.endswith('.json') and f[:-5] not in por_anio:
            os.remove(os.path.join(carpeta, f))
    for a, xs in por_anio.items():
        # La tipología se recalcula siempre: un cambio en config/tipologias.json alcanza a todas.
        for x in xs:
            x['tipol'] = tipologia(x['nom'])
        xs.sort(key=lambda x: (x.get('fadj') or x['fpub'] or '', x['cod']), reverse=True)
        json.dump({'campos': CAMPOS, 'filas': [[x.get(c) for c in CAMPOS] for x in xs]},
                  open(os.path.join(carpeta, f'{a}.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))


def escribir_indice(publico):
    base = os.path.join(publico, 'mp')
    regiones = {}
    for reg in sorted(os.listdir(base)):
        carpeta = os.path.join(base, reg)
        if not os.path.isdir(carpeta):
            continue
        regiones[reg] = {f[:-5]: len(json.load(open(os.path.join(carpeta, f), encoding='utf-8'))['filas'])
                         for f in sorted(os.listdir(carpeta)) if f.endswith('.json')}
    nombres = {slug: nom for slug, nom, _ in REGIONES}
    json.dump({'actualizado': time.strftime('%Y-%m-%d'), 'tipos': FILTROS['tipos'],
               'regiones': {r: {'nombre': nombres.get(r, r), 'anios': a} for r, a in regiones.items()}},
              open(os.path.join(base, 'indice.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

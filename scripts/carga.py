"""Carga desde los datos abiertos de ChileCompra (archivos mensuales de licitaciones).

Cada archivo <año>-<mes>.zip trae las licitaciones PUBLICADAS ese mes, una fila por ítem y
oferta, con su estado a la fecha en que ChileCompra lo regeneró. Procesar un mes reemplaza
en los archivos publicados todas las licitaciones de la región publicadas ese mes (clave:
código), así que correrlo dos veces no duplica filas.

Uso:
  python scripts/carga.py --publico public --ultimos 60       # carga inicial (5 años)
  python scripts/carga.py --publico public --ultimos 3        # conciliación
  python scripts/carga.py --publico public --meses 2025-9 2025-10
"""
import argparse, csv, io, os, sys, tempfile, time, urllib.request, zipfile, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comun import FILTROS, region_slug, es_obra, num, cargar_uf, completar, leer_region, escribir_region, escribir_indice, rellenar_uf

URL = 'https://transparenciachc.blob.core.windows.net/lic-da/{}.zip'


def meses_ultimos(n):
    a, m = time.localtime().tm_year, time.localtime().tm_mon
    out = []
    for _ in range(n):
        out.append(f'{a}-{m}')
        a, m = (a, m - 1) if m > 1 else (a - 1, 12)
    return out[::-1]


def bajar(mes, carpeta):
    ruta = os.path.join(carpeta, f'{mes}.zip')
    if not os.path.exists(ruta):
        for k in range(4):
            try:
                urllib.request.urlretrieve(URL.format(mes), ruta)
                break
            except Exception as e:
                if getattr(e, 'code', None) == 404:
                    return None
                if k == 3:
                    raise
                time.sleep(2 ** k)
    return ruta


def procesar_mes(ruta):
    """Licitaciones adjudicadas que cumplen los filtros, agrupadas por código: {reg: {cod: dict}}."""
    z = zipfile.ZipFile(ruta)
    rd = csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding='cp1252', errors='replace', newline=''), delimiter=';')
    out, vistos = collections.defaultdict(dict), collections.Counter()
    for r in rd:
        reg = region_slug(r['RegionUnidad'])
        if reg not in FILTROS['regiones'] or not r['Estado'].startswith('Adjudicada'):
            continue
        cod = r['CodigoExterno'].strip()
        L = out[reg].get(cod)
        if L is None:
            if cod in vistos or not es_obra(r['Tipo'], r['Nombre'], r['Obras']):
                vistos[cod] += 1
                continue
            L = out[reg][cod] = dict(
                cod=cod, nom=r['Nombre'].strip(), org=r['NombreOrganismo'].strip(), reg=reg, com=r['ComunaUnidad'].strip(),
                tipo=r['Tipo'], fpub=r['FechaPublicacion'][:10], fadj=(r['FechaAdjudicacion'] or '')[:10] or None,
                mon=r['CodigoMoneda'].strip(), est=num(r['MontoEstimado']) or None, adj=0.0,
                ofe=int(num(r['NumeroOferentes'])) or None, prov={}, desc=r['Descripcion'])
        if r['Oferta seleccionada'].lower().startswith('selec'):
            L['adj'] += num(r['MontoLineaAdjudica']) or num(r['CantidadAdjudicada']) * num(r['MontoUnitarioOferta'])
            L['prov'][r['RutProveedor'].strip()] = r['RazonSocialProveedor'].strip() or r['NombreProveedor'].strip()
    for lics in out.values():
        for L in lics.values():
            L['adj'] = round(L['adj'], 2)
            L['prov'] = [f'{n} ({rut})' for rut, n in L['prov'].items()]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--publico', required=True, help='carpeta publicada (contiene mp/)')
    ap.add_argument('--ultimos', type=int)
    ap.add_argument('--meses', nargs='*')
    ap.add_argument('--zips', help='carpeta donde guardar/leer los .zip (por defecto, temporal)')
    a = ap.parse_args()
    meses = a.meses or meses_ultimos(a.ultimos or 3)
    carpeta = a.zips or tempfile.mkdtemp()
    os.makedirs(carpeta, exist_ok=True)
    nuevos = collections.defaultdict(dict)
    procesados = set()
    for mes in meses:
        ruta = bajar(mes, carpeta)
        if not ruta:
            print(mes, 'sin archivo'); continue
        por_reg = procesar_mes(ruta)
        procesados.add('%04d-%02d' % tuple(map(int, mes.split('-'))))
        for reg, lics in por_reg.items():
            nuevos[reg].update(lics)
        print(mes, {r: len(l) for r, l in por_reg.items()}, flush=True)
        if not a.zips:
            os.remove(ruta)
    uf = cargar_uf(a.publico, [int(m[:4]) for m in procesados] + [time.localtime().tm_year])
    for reg in FILTROS['regiones']:
        actual = leer_region(a.publico, reg)
        # Reemplaza lo publicado en los meses procesados (lo que ya no cumple el filtro se va).
        actual = {c: x for c, x in actual.items() if x['fpub'][:7] not in procesados}
        for c, L in nuevos[reg].items():
            actual[c] = completar(L, uf)
        rellenar_uf(actual, uf)
        escribir_region(a.publico, reg, actual)
        n = collections.Counter(((x.get('fadj') or x['fpub'])[:4], x['tipo']) for x in actual.values())
        print(reg, len(actual), dict(sorted(n.items())))
    escribir_indice(a.publico)


if __name__ == '__main__':
    main()

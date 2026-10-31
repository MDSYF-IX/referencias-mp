"""Actualización diaria desde la API de Mercado Público (requiere el secreto MP_TICKET).

1. licitaciones.json?fecha=<ayer>&estado=adjudicada  (una consulta, nacional)
2. Prefiltro por el tipo del sufijo del código (LR, I2, O1, O2) y por palabras de no-obra.
3. Detalle de cada una (una consulta por licitación); se queda con las de las regiones de
   config/filtros.json que cumplen el filtro de obras.
4. Agrega o reemplaza (clave: código) en el archivo del año y actualiza indice.json.

Sin MP_TICKET no hace nada: la carga sigue saliendo de los datos abiertos (carga.py).
Campos verificados con una respuesta real (30-10-2026). «fecha» con estado=adjudicada es la
fecha de adjudicación (Fechas.FechaAdjudicacion). Ver una respuesta: --muestra CODIGO.

Uso: python scripts/diaria.py --publico public [--fecha DDMMAAAA]
"""
import argparse, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comun import FILTROS, norm, region_slug, tipo_de_codigo, es_obra, num, get_json, cargar_uf, completar, leer_region, escribir_region, escribir_indice, rellenar_uf, _tiene, estado_norm, combinar

BASE = 'https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json'
LIMITE = 9000


class Contador:
    n = 0

    @classmethod
    def get(cls, url):
        if cls.n >= LIMITE:
            raise RuntimeError(f'Se alcanzó el límite interno de {LIMITE} consultas')
        cls.n += 1
        return get_json(url)


def fecha_iso(s):
    return str(s or '')[:10] or None


def desde_detalle(d):
    """Licitación de la API → mismos campos que carga.py (sin los calculados)."""
    comp, fechas = d.get('Comprador') or {}, d.get('Fechas') or {}
    adj, prov = 0.0, {}
    for it in ((d.get('Items') or {}).get('Listado') or []):
        a = it.get('Adjudicacion') or {}
        if a.get('RutProveedor'):
            adj += num(a.get('Cantidad')) * num(a.get('MontoUnitario'))
            prov[a['RutProveedor']] = a.get('NombreProveedor') or ''
    return dict(
        cod=d['CodigoExterno'], nom=(d.get('Nombre') or '').strip(), org=(comp.get('NombreOrganismo') or '').strip(),
        reg=region_slug(comp.get('RegionUnidad')), com=(comp.get('ComunaUnidad') or '').strip(),
        tipo=d.get('Tipo') or tipo_de_codigo(d['CodigoExterno']), fpub=fecha_iso(fechas.get('FechaPublicacion')),
        estado=estado_norm(d.get('Estado')), fcie=fecha_iso(fechas.get('FechaCierre')),
        fadj=fecha_iso(fechas.get('FechaAdjudicacion')), mon=d.get('Moneda') or 'CLP', est=num(d.get('MontoEstimado')) or None,
        adj=round(adj, 2), ofe=int(num((d.get('Adjudicacion') or {}).get('NumeroOferentes'))) or None,
        prov=[f'{n} ({r})' for r, n in prov.items()], desc=d.get('Descripcion') or '', obras=d.get('Obras'),
        bip=str(d['CodigoBIP']).strip() if d.get('CodigoBIP') else None)


def publicadas(publico, ticket, nuevas, errores):
    """Licitaciones publicadas (abiertas a ofertas) hoy: datos abiertos no las trae hasta que
    cierran. Se pide el detalle solo de las que no se han visto: las ya publicadas y las
    descartadas (otra región, no obra) se recuerdan en cache/activas_descartadas.json."""
    ruta = os.path.join(publico, 'cache', 'activas_descartadas.json')
    descartadas = set(json.load(open(ruta, encoding='utf-8'))) if os.path.exists(ruta) else set()
    try:
        act = Contador.get(f'{BASE}?estado=activas&ticket={ticket}').get('Listado') or []
    except Exception as e:
        errores.append(f'activas: {e}'); return 0
    vigentes = {x.get('CodigoExterno') for x in act}
    conocidas = {c for reg in FILTROS['regiones'] for c in leer_region(publico, reg)} | set(nuevas) | descartadas
    pre = [x for x in act if tipo_de_codigo(x.get('CodigoExterno')) in FILTROS['tipos'] and x.get('CodigoExterno') not in conocidas
           and not _tiene(FILTROS['palabras_no_obras'], norm(x.get('Nombre')))]
    n = 0
    try:
        for x in pre:
            try:
                det = (Contador.get(f"{BASE}?codigo={x['CodigoExterno']}&ticket={ticket}").get('Listado') or [None])[0]
            except RuntimeError:
                raise
            except Exception as e:
                errores.append(f"{x['CodigoExterno']}: {e}"); continue
            L = desde_detalle(det) if det else None
            if L and L['estado'] and L['reg'] in FILTROS['regiones'] and es_obra(L['tipo'], L['nom'], L.pop('obras')):
                nuevas[L['cod']] = L; n += 1
            else:
                descartadas.add(x['CodigoExterno'])
    except RuntimeError as e:
        print(e)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    json.dump(sorted(descartadas & vigentes), open(ruta, 'w', encoding='utf-8'))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--publico', required=True)
    ap.add_argument('--fecha', help='DDMMAAAA; por defecto, ayer')
    ap.add_argument('--desde', help='relleno: primer día (AAAA-MM-DD) de un rango de fechas de adjudicación')
    ap.add_argument('--hasta', help='relleno: último día (AAAA-MM-DD); por defecto, ayer')
    ap.add_argument('--muestra', help='imprime la respuesta cruda del detalle de un código y termina')
    a = ap.parse_args()
    ticket = os.environ.get('MP_TICKET')
    if not ticket:
        print('Sin MP_TICKET: se omite la actualización diaria por API.')
        return
    if a.muestra:
        print(json.dumps(Contador.get(f'{BASE}?codigo={a.muestra}&ticket={ticket}'), ensure_ascii=False, indent=1)[:6000])
        return
    ayer = datetime.date.today() - datetime.timedelta(days=1)
    if a.desde:
        # Relleno: los archivos de datos abiertos de meses pasados se regeneran cada varios
        # meses, así que lo adjudicado después queda fuera hasta entonces; la API lo trae.
        d0, d1 = datetime.date.fromisoformat(a.desde), datetime.date.fromisoformat(a.hasta) if a.hasta else ayer
        fechas = [(d0 + datetime.timedelta(days=k)).strftime('%d%m%Y') for k in range((d1 - d0).days + 1)]
    else:
        fechas = [a.fecha or ayer.strftime('%d%m%Y')]
    # Las ya publicadas no se vuelven a pedir (ahorra consultas en el relleno).
    conocidas = {c for reg in FILTROS['regiones'] for c in leer_region(a.publico, reg)} if a.desde else set()
    nuevas, descartadas, errores, n_lista, n_pre, ultima = {}, 0, [], 0, 0, None
    try:
        for fecha in fechas:
            lista = Contador.get(f'{BASE}?fecha={fecha}&estado=adjudicada&ticket={ticket}').get('Listado') or []
            pre = [x for x in lista if tipo_de_codigo(x.get('CodigoExterno')) in FILTROS['tipos']
                   and not _tiene(FILTROS['palabras_no_obras'], norm(x.get('Nombre'))) and x.get('CodigoExterno') not in conocidas]
            n_lista += len(lista); n_pre += len(pre)
            for x in pre:
                try:
                    det = (Contador.get(f"{BASE}?codigo={x['CodigoExterno']}&ticket={ticket}").get('Listado') or [None])[0]
                except RuntimeError:
                    raise
                except Exception as e:
                    errores.append(f"{x['CodigoExterno']}: {e}"); continue
                if not det:
                    continue
                L = desde_detalle(det)
                if L['reg'] in FILTROS['regiones'] and es_obra(L['tipo'], L['nom'], L.pop('obras')):
                    nuevas[L['cod']] = L
                else:
                    descartadas += 1
            ultima = fecha
    except RuntimeError as e:
        # Límite de consultas: se guarda lo obtenido y se informa hasta qué día se llegó.
        print(f'{e}. Último día completo: {ultima or "ninguno"}; continuar desde el día siguiente.')
    fecha = fechas[0] if len(fechas) == 1 else f'{fechas[0]} a {ultima}'
    n_act = publicadas(a.publico, ticket, nuevas, errores) if not a.desde else 0
    if nuevas:
        uf = cargar_uf(a.publico, {int((L['fadj'] or L['fpub'])[:4]) for L in nuevas.values()})
        for reg in FILTROS['regiones']:
            actual = leer_region(a.publico, reg)
            for c, L in nuevas.items():
                if L['reg'] == reg:
                    actual[c] = combinar(actual.get(c), completar(L, uf))
            rellenar_uf(actual, uf)
            escribir_region(a.publico, reg, actual)
        escribir_indice(a.publico)
    print(f'Fecha {fecha}: {n_lista} adjudicadas en el país, {n_pre} pasan el prefiltro, '
          f'{len(nuevas)} nuevas o actualizadas ({n_act} publicadas), {descartadas} descartadas, {len(errores)} errores, {Contador.n} consultas.')
    for e in errores:
        print('  ERROR', e)


if __name__ == '__main__':
    main()

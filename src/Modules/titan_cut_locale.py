"""Localização da interface do Titan Cut. Nunca traduz nomes de arquivo."""
import re

LANGUAGES = ('pt-BR', 'en', 'es')
LANGUAGE_NAMES = ('Português (Brasil)', 'English', 'Español')
LANG = 'pt-BR'

# Português (fonte) | English | Español
ROWS = '''
Titan Cut|Titan Cut|Titan Cut
Analisar timeline|Analyze timeline|Analizar timeline
Analisando…|Analyzing…|Analizando…
Parar|Stop|Detener
Criar marcadores|Create markers|Crear marcadores
Criar subclipes|Create subclips|Crear subclips
Limiar de score|Score threshold|Umbral de puntuación
Foco|Focus|Enfoque
Exposição|Exposure|Exposición
Movimento|Motion|Movimiento
Peso das métricas|Metric weighting|Ponderación de métricas
Score geral|Overall score|Puntuación general
Clipe|Clip|Clip
Duração|Duration|Duración
Selects encontrados|Selects found|Selects encontrados
Nenhum select encontrado com o limiar atual.|No selects found at the current threshold.|No se encontraron selects con el umbral actual.
Nenhuma timeline aberta no Resolve.|No timeline open in Resolve.|No hay timeline abierto en Resolve.
Nenhum clipe na timeline atual.|No clips on the current timeline.|No hay clips en el timeline actual.
Conectado ao Resolve.|Connected to Resolve.|Conectado a Resolve.
Não foi possível conectar ao Resolve. Abra o Titan Cut pelo menu Workspace > Scripts.|Could not connect to Resolve. Open Titan Cut from Workspace > Scripts menu.|No se pudo conectar a Resolve. Abre Titan Cut desde el menú Workspace > Scripts.
Marcadores criados: %s|Markers created: %s|Marcadores creados: %s
Analisando clipe %s de %s…|Analyzing clip %s of %s…|Analizando clip %s de %s…
Fechar|Close|Cerrar
Sobre|About|Acerca de
Idioma|Language|Idioma
Taxa de amostragem|Sample rate|Tasa de muestreo
Configurações|Settings|Configuración
'''

TABLE = {}
for row in ROWS.strip().splitlines():
    source, en, es = row.split('|')
    TABLE[source] = {'en': en, 'es': es}


def configure(language):
    global LANG
    LANG = language if language in LANGUAGES else 'pt-BR'
    return LANG


def translate(text):
    if not isinstance(text, str) or LANG == 'pt-BR':
        return text
    if text.strip() != text and text.strip():
        start = len(text) - len(text.lstrip())
        end = len(text.rstrip())
        return text[:start] + translate(text[start:end]) + text[end:]
    if text in TABLE:
        return TABLE[text][LANG]
    if '<' in text and '>' in text:
        return re.sub(r'(?<=>)[^<>]+(?=<)', lambda m: translate(m.group(0)), text)
    for template, targets in TABLE.items():
        if '%' not in template:
            continue
        tokens = re.findall(r'%(?:\.\d+)?[sdf]|%%', template)
        pattern = re.escape(template)
        for token in tokens:
            pattern = pattern.replace(re.escape(token), '%' if token == '%%' else '(.+?)', 1)
        match = re.fullmatch(pattern, text)
        if match:
            groups = iter(match.groups())
            return re.sub(
                r'%(?:\.\d+)?[sdf]|%%',
                lambda m: '%' if m.group(0) == '%%' else next(groups),
                targets[LANG],
            )
    return text


class UIProxy:
    """Envolve o UIManager do Fusion para traduzir Text/ToolTip/PlaceholderText
    automaticamente em cada chamada de criação de widget."""

    def __init__(self, raw):
        self.raw = raw

    def __getattr__(self, name):
        target = getattr(self.raw, name)
        if not callable(target):
            return target

        def call(*args, **kwargs):
            args = list(args)
            if args and isinstance(args[0], dict):
                props = dict(args[0])
                for key in ('Text', 'ToolTip', 'PlaceholderText'):
                    if key in props:
                        props[key] = translate(props[key])
                args[0] = props
            return target(*args, **kwargs)

        return call


class WidgetProxy:
    """Envolve um widget individual para traduzir leituras/escritas de texto."""

    def __init__(self, raw, identity):
        object.__setattr__(self, 'raw', raw)
        object.__setattr__(self, 'identity', identity)

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def __setattr__(self, name, value):
        if name in ('Text', 'ToolTip') and isinstance(value, str):
            value = translate(value)
        setattr(self.raw, name, value)


def wrap_items(items):
    return {key: WidgetProxy(value, key) for key, value in items.items()}

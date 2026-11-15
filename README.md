# Claude Code Dictation

Dictado global para Linux X11 usando el reconocimiento de voz de **Claude Code**. Mantén **Ctrl+Alt+J**, habla y suelta para pegar el resultado en la aplicación activa. **Esc** cancela.

El reconocimiento lo realiza Anthropic en la nube. Este proyecto controla el cliente oficial y recoge la transcripción; no incluye un modelo de voz local ni necesita una API de pago por uso. Proyecto independiente, sin afiliación con Anthropic.

## Requisitos

- **Sesión gráfica X11** con acceso al micrófono e Internet. Probado en Ubuntu 24.04 y GNOME X11. No admite Wayland, Windows, macOS ni ejecución remota por SSH.
- **Claude Code instalado y autenticado con una cuenta Claude.ai que tenga acceso a `/voice`**. Primero comprueba el dictado en el propio cliente. Versión probada: **2.1.325**; otras versiones pueden cambiar la interfaz o las opciones necesarias.
- **Python 3.10 o posterior**, con **Tkinter**.
- **`xclip`, `xprop`, libX11 y libXtst**.
- Una aplicación que acepte pegar con **Ctrl+V** o **Ctrl+Shift+V**. No se ha comprobado compatibilidad con todas las aplicaciones.

Dependencias en Ubuntu/Debian:

```sh
sudo apt install git python3 python3-tk xclip x11-utils libx11-6 libxtst6 alsa-utils
```

`alsa-utils` proporciona `arecord`, una alternativa de captura que Claude puede necesitar. Las dependencias Python `pyte` y `wcwidth` están incluidas en `vendor`; no hace falta ejecutar `pip`.

Instala y autentica Claude siguiendo su [documentación oficial](https://code.claude.com/docs/en/setup). Ejecuta `claude`, completa el inicio de sesión y prueba `/voice` antes de continuar. El puente utiliza el archivo de credenciales del perfil local; no implementa otros almacenes de autenticación.

## Inicio rápido

```sh
git clone https://github.com/diegomarzaa/claude-code-dictation.git
cd claude-code-dictation
./start.sh
```

Espera al mensaje **Listo**, coloca el cursor en un campo de texto y mantén **Ctrl+Alt+J** mientras hablas. Suelta para terminar y pegar. Aparecerán indicadores de escucha, procesamiento y fin.

Deja la terminal del puente abierta. Para detenerlo, pulsa **Ctrl+C** en ella o ejecuta `./stop.sh` desde otra terminal, dentro de la misma carpeta. El arranque es manual; no se instala ningún servicio ni se necesita un asistente de IA para ejecutarlo.

## Opciones

```sh
./start.sh --language english      # español por defecto
./start.sh --live                  # vista previa flotante del texto provisional
./start.sh --key u                 # cambia el atajo a Ctrl+Alt+U
./start.sh --terminal              # fuerza el pegado con Ctrl+Shift+V
./start.sh --claude ./bin/claude    # ejecutable alternativo
./start.sh --claude-config "$HOME/.claude-work"  # perfil alternativo
python3 dictate.py status
python3 dictate.py cancel
```

Claude se busca en `PATH`; también se puede indicar mediante `CLAUDE_BIN`. El perfil se obtiene de `--claude-config`, `CLAUDE_CONFIG_DIR` o, por defecto, `~/.claude`.

Si utilizas un entorno Python sin Tkinter, selecciona un intérprete que lo incluya mediante `PYTHON` al arrancar y parar. Por ejemplo, `PYTHON=python3.12 ./start.sh`. La carpeta del proyecto se puede mover; sus rutas se calculan al arrancar. Detén el proceso antes de moverla.

`--live` muestra texto provisional **en una ventana flotante** y pega solo el resultado final. No escribe ni corrige texto dentro del editor mientras hablas. El modo normal muestra únicamente los indicadores de estado.

## Cómo funciona

1. El puente arranca Claude en una **PTY**, una terminal controlada por código y sin ventana propia.
2. El atajo envía pulsaciones a Claude para iniciar y terminar el dictado. **Claude captura el audio, lo envía a Anthropic y recibe la transcripción**; el audio no pasa por la PTY.
3. Un hook `UserPromptSubmit` entrega el texto final al puente por un socket local y responde `continue:false`. Si el hook falla, `onFailure:block` impide continuar con ese mensaje.
4. El puente pega el texto en la ventana de destino, sin enviar Enter a esa aplicación. La vista previa opcional lee el campo de entrada de la terminal mediante `pyte`.

## Cuenta y datos

- La instancia usa su propia configuración y perfiles en `state/`, con herramientas, skills y servidores MCP desactivados mediante las opciones de arranque. Los perfiles aislados enlazan el archivo de credenciales existente; el cliente puede renovar esas credenciales.
- El puente no configura facturación por API. Según la [documentación de voz](https://code.claude.com/docs/en/voice-dictation), la transcripción no consume mensajes ni tokens de Claude. El cliente puede hacer llamadas auxiliares, como generar un título de sesión.
- El audio se procesa en los servidores de Anthropic. El puente no guarda archivos de audio; sí guarda el último texto en `state/last.txt`, y Claude puede guardar historial en sus perfiles aislados.
- `state/` es privado para el usuario del sistema y está excluido de Git. No compartas esa carpeta. Detén el puente antes de eliminarla para borrar su estado local; los datos de Anthropic se rigen por su política de uso de datos.

## Límites y resolución de problemas

- **Mantén el cursor en el campo de destino.** Si cambia el foco de X11, el puente omite el pegado. Una selección activa se reemplaza al pegar, como en un pegado manual; no puede detectar todos los movimientos dentro de una misma ventana.
- El portapapeles solo se restaura como texto cuando es posible; no conserva imágenes ni formatos enriquecidos. Los saltos de línea del dictado se convierten en espacios.
- Si el atajo está ocupado, el programa se niega a registrarlo. Usa `--key` para elegir otro; se rechazan Ctrl+Alt+F1…F12 porque cambian de consola virtual en Linux.
- Si una terminal integrada no recibe el texto, prueba `--terminal`. La detección automática de terminales se basa en la clase de la ventana.
- Si no se reconoce voz, comprueba primero `/voice` en Claude. Las grabaciones tienen los límites del cliente: hasta dos minutos y parada tras quince segundos de silencio.
- La detección de fin y el envío de frases cortas dependen de la interfaz de Claude. Actualizar el cliente puede requerir adaptar este puente.

**Estado de validación:** el dictado con pegado final se ha probado con voz real en Ubuntu 24.04, GNOME X11 y Claude Code 2.1.325. Los indicadores gráficos nuevos, la vista previa y los cambios de portabilidad aún no se han validado de extremo a extremo. No se garantiza funcionamiento en otras combinaciones.

## Licencia y referencias

Código del puente bajo [licencia MIT](LICENSE). Las dependencias conservan sus propias licencias; consulta [THIRD_PARTY.md](THIRD_PARTY.md).

El patrón de instancia dedicada y captura mediante hook se inspira en [android6/claude-dictate](https://github.com/android6/claude-dictate), una implementación para Windows. Este puente tiene implementación propia para Linux.

Fuentes oficiales, consultadas el 15/11/2026: [dictado](https://code.claude.com/docs/en/voice-dictation), [hooks](https://code.claude.com/docs/en/hooks) e [instalación](https://code.claude.com/docs/en/setup).

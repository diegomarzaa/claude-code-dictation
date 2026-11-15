# Dictado global con Claude Code · Ubuntu X11

Puente independiente para el cliente oficial. Mantén **Ctrl+Alt+J**, habla y suelta para pegar. **Esc** cancela durante la grabación o el procesamiento. No pulsa Enter en la aplicación receptora.

## Uso

Desde esta carpeta:

```sh
./start.sh                         # español, pega al terminar
./stop.sh                          # detener desde otra terminal
./start.sh --language english      # inglés
./start.sh --live                  # vista previa flotante en directo
./start.sh --key u                 # Ctrl+Alt+U
./dictate.py status
./dictate.py cancel
```

Puedes arrancarlo tú directamente desde cualquier terminal, sin Codex ni este chat:

```sh
~/Documents/Github/Professional/claude-code-dictation/start.sh
```

Para pararlo, pulsa **Ctrl+C** en esa terminal o ejecuta `stop.sh` desde otra. Deja abierto el proceso de `start.sh`. No se ha instalado ningún servicio ni inicio automático. Solo registra su atajo mientras está ejecutándose; si está ocupado, se niega a arrancar. No cambia atajos de GNOME ni nada de Vocalinux. Para volver al comportamiento anterior basta detenerlo.

La clase de la ventana determina si pega con Ctrl+V o Ctrl+Shift+V. En terminales integradas que no detecte automáticamente, usa `--terminal`. Conserva texto del portapapeles cuando puede; no conserva formatos enriquecidos ni imágenes. La ventana y el cursor deben mantenerse en el mismo campo durante todo el dictado. Si cambia el foco de X11, deja de insertar y guarda el resultado en `state/last.txt`.

## Indicadores de estado

El modo normal también muestra un indicador flotante: «Escuchando…» mientras mantienes el atajo, «Procesando…» al soltar y «Texto pegado» al terminar. También indica cancelación, ausencia de voz o error de pegado. Los avisos de fin desaparecen solos. El indicador no toma el foco ni inserta mensajes temporales en el campo de texto.

Estos indicadores nuevos aún no se han probado visualmente. Inicia `start.sh` para cargar esta versión.

## Vista previa en directo

`--live` muestra el texto provisional en una ventana flotante, sin tomar el foco, mientras hablas. Solo pega el resultado final al soltar el atajo, igual que el modo normal. Esc cancela y oculta la vista previa. No envía retrocesos, no reemplaza fragmentos provisionales y no escribe durante la grabación en el editor receptor.

La antigua inserción progresiva dentro del editor fue retirada tras un borrado de texto durante una prueba real. No podía verificar la posición del cursor ni los modificadores mientras corregía texto. El nuevo `--live` es una vista previa, no inserción progresiva dentro de la aplicación.

El lector sigue dependiendo de la pantalla de Claude en una PTY. La nueva vista previa aún no se ha probado con audio real. El modo normal sí ha funcionado en las pruebas de Diego. Mantén el cursor en el campo de destino para el pegado final. Como al pegar manualmente, una selección activa será reemplazada por el resultado final.

## Aislamiento y cuenta

- Arranca `~/.local/bin/claude` en una PTY dedicada, sin herramientas, skills ni servidores MCP de usuario/proyecto.
- Usa `state/profile` como `CLAUDE_CONFIG_DIR`, con enlace al archivo de credenciales existente. No muestra ni copia el token y no configura una API de pago.
- Solo copia los metadatos de onboarding y cuenta necesarios al perfil aislado. Claude puede renovar sus propias credenciales de la manera habitual.
- Usa opciones de voz e idioma en `state/settings.json`; no edita la configuración habitual de Claude.
- Un hook `UserPromptSubmit` captura el texto y responde `continue:false`; si falla, `onFailure:block` impide que el prompt siga al modelo. Diego ha confirmado que el modo de pegado final funciona con voz real.
- Claude puede solicitar un título de sesión en segundo plano con Haiku; no se promete ausencia absoluta de llamadas auxiliares del cliente. La transcripción en sí está incluida en la cuenta según la documentación oficial.
- El audio lo procesa Anthropic. No se graba audio en archivos por parte del puente. Claude puede guardar su historial en el perfil aislado y el resultado final queda en `state/last.txt`. `state` tiene permisos 0700; no lo compartas.

## Estado al 15/11/2026

Claude Code 2.1.325 arranca con Claude Pro en el perfil aislado. Diego ha confirmado que el modo normal transcribe y pega correctamente. La nueva vista previa flotante no se ha probado aún con micrófono real; se han comprobado las restricciones que impiden borrar texto mediante retrocesos. El arranque es manual; no se instala ningún servicio.

Claude limita las grabaciones a dos minutos y puede pararlas tras quince segundos de silencio. El puente intenta enviar con Enter los resultados cortos que tap mode deja sin enviar; esa detección depende de la interfaz y permanece sin probar. Se evitan Ctrl+Alt+F1…F12 porque Linux los reserva para cambiar de consola virtual. El servicio admite español e inglés seleccionados por sesión; la calidad al mezclarlos no está comprobada.

## Fuentes y dependencias

Consultadas el 15/11/2026:

- [Voz oficial](https://code.claude.com/docs/en/voice-dictation)
- [Hooks oficiales](https://code.claude.com/docs/en/hooks)
- [Antecedente Windows](https://github.com/android6/claude-dictate): referencia del patrón de captura con hook; implementación de este puente independiente.

Incluye pyte 0.8.2 y wcwidth 0.9.4 en `vendor`, con sus licencias. Requiere Python 3 del sistema, libX11, libXtst, xclip y xprop, presentes en esta máquina. Requiere GNOME X11; no implementa Wayland.

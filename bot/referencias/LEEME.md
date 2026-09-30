# Fotos de referencia para la IA

Ejemplos reales de la empresa que se le muestran a la IA junto a cada foto de reparación, para
que distinga cada elemento (sobre todo tapa de acceso vs. tapa de inspección, que pueden medir
lo mismo). Una carpeta por elemento, con este nombre exacto:

```
bot/referencias/
  tapa_acceso/       tapas de acceso (cuadradas, octagonales con parantes, punta recortada, 12 agujeros)
  tapa_inspeccion/   tapas de inspección (de entrada de agua y ciegas)
  tapa_inspeccion_faltante/  lugares donde debería haber una tapa de inspección y solo está el agujero
  marco/             marcos, sin tapa o la unión tapa-marco
  pared_revoque/     revoques de paredes y piso (en buen y en mal estado)
  piso/              pisos del tanque
```

- Hasta `VISION_MAX_REF` fotos por carpeta (10 por defecto), en orden alfabético.
- JPEG o PNG. Se achican a 768 px al cargarse; conviene subirlas ya achicadas y **sin datos EXIF**
  (el repo es público y las fotos del celular traen la ubicación GPS).
- Sin personas, direcciones ni carteles del edificio.
- Variedad: distintos tamaños, ángulos, luz y estado (buenas y dañadas).
- Si una carpeta no existe o está vacía, la IA trabaja sin ejemplos de ese elemento.

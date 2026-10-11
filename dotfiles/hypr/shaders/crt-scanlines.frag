#version 300 es
// Light CRT: keeps real colors and adds scanlines, a vignette and a faint
// warm cast in the shadows. Static, so it only costs GPU when the screen changes.
precision highp float;

in vec2 v_texcoord;
uniform sampler2D tex;
layout(location = 0) out vec4 fragColor;

void main() {
    vec4 src = texture(tex, v_texcoord);
    vec3 col = src.rgb;

    float row = floor(v_texcoord.y * float(textureSize(tex, 0).y));
    col *= mod(row, 2.0) < 1.0 ? 1.0 : 0.86;

    vec2 d = v_texcoord - 0.5;
    col *= 1.0 - dot(d, d) * 0.45;

    col = mix(col, col * vec3(1.0, 0.92, 0.78), 0.25);

    fragColor = vec4(col, src.a);
}

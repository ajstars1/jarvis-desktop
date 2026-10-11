#version 300 es
// Full amber CRT: every pixel becomes amber phosphor on warm black,
// plus scanlines and a soft vignette. There's no `time` uniform, so the
// GPU only works when the screen actually changes.
// No screen curvature on purpose: it would put clicks off from what you see.
precision highp float;

in vec2 v_texcoord;
uniform sampler2D tex;
layout(location = 0) out vec4 fragColor;

const vec3 BG    = vec3(0.071, 0.043, 0.000);   // #120b00
const vec3 AMBER = vec3(1.000, 0.690, 0.000);   // #ffb000
const vec3 HOT   = vec3(1.000, 0.824, 0.478);   // #ffd27a

void main() {
    vec4 src = texture(tex, v_texcoord);
    float lum = dot(src.rgb, vec3(0.299, 0.587, 0.114));

    // phosphor ramp: black to amber, the brightest whites glow hot
    vec3 col = mix(BG, AMBER, smoothstep(0.0, 0.85, lum));
    col = mix(col, HOT, smoothstep(0.85, 1.0, lum));

    // scanlines: every other pixel row is a little darker
    float row = floor(v_texcoord.y * float(textureSize(tex, 0).y));
    col *= mod(row, 2.0) < 1.0 ? 1.0 : 0.82;

    // vignette: the corners fall off like curved glass
    vec2 d = v_texcoord - 0.5;
    col *= 1.0 - dot(d, d) * 0.55;

    fragColor = vec4(col, src.a);
}

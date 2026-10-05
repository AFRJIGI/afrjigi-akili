"""Notation des maths et de la physique-chimie sur WhatsApp (LaTeX -> texte lisible)."""
import unittest

import main

CAS = [
    (r"$f'(x) = \frac{2x+1}{(x-1)^2}$", "f'(x) = (2x+1)/((x-1)²)"),
    (r"$\frac{\sqrt{3}}{2}$ et $\frac{1}{\sqrt{2}}$", "√3/2 et 1/√2"),
    (r"$\lim_{x \to +\infty} \frac{e^x}{x} = +\infty$", "lim(x → +∞) (e^x)/x = +∞"),
    (r"$\int_0^1 x^2 \, dx = \frac{1}{3}$", "∫ de 0 à 1 x² dx = 1/3"),
    (r"$u_{n+1} = 2u_n + 3$ et $u_0 = 1$", "uₙ₊₁ = 2uₙ + 3 et u₀ = 1"),
    (r"$e^{-x}$ et $e^{2x-1}$", "e^(-x) et e^(2x-1)"),
    (r"$f(x) = (3x-1)e^{2x}$", "f(x) = (3x-1)e^(2x)"),
    # cas releves dans l'enquete du 5 octobre (messages reellement envoyes)
    (r"$V_i = \frac{A_{i-1}A_{i+1}}{2\tau}$", "Vᵢ = (Aᵢ₋₁Aᵢ₊₁)/(2τ)"),
    (r"$\lim_{x \to -\infty} x^4 = \dots$", "lim(x → -∞) x⁴ = …"),
    (r"$\frac{2 - \sqrt{x+1}}{x-3}$", "(2 - √(x+1))/(x-3)"),
    (r"$\frac{\sqrt{2x^2+1}}{x^2+3}$", "√(2x²+1)/(x²+3)"),
    (r"$r = \sqrt{(-\sqrt{3})^2 + 1^2} = 2$", "r = √((-√3)² + 1²) = 2"),
    (r"$u_s = k \times \frac{du_e}{dt}$", "uₛ = k × duₑ/dt"),
    (r"$(ax^n)' = nax^{n-1}$", "(axⁿ)' = naxⁿ⁻¹"),
    (r"$F_4(x) = \frac{\cos(x)+1}{x-\pi}$", "F₄(x) = (cos(x)+1)/(x-π)"),
    ("Le temps \\tau entre deux positions", "Le temps τ entre deux positions"),
    ("Profil prêt : BAC_GENERAL, série D", "Profil prêt : BAC GENERAL, série D"),
    (r"$\left(\frac{1}{2}\right)^n$", "(1/2)ⁿ"),
    (r"$x \in \mathbb{R}$, $x \leq 3$, $x \neq 0$", "x ∈ ℝ, x ≤ 3, x ≠ 0"),
    (r"$x_1 = \frac{-b - \sqrt{\Delta}}{2a}$", "x₁ = (-b - √Δ)/(2a)"),
    (r"$\text{Si } x > 0 \text{ alors } f(x) > 0$", "Si x > 0 alors f(x) > 0"),
    (r"$C = 0{,}1 \text{ mol} \cdot \text{L}^{-1}$", "C = 0,1 mol · L⁻¹"),
    (r"$\ce{H2SO4}$, $\text{SO}_4^{2-}$, $\mathrm{CO_2}$", "H₂SO₄, SO₄²⁻, CO₂"),
    (r"$v = 3{,}0 \times 10^{8} \ m.s^{-1}$", "v = 3,0 × 10⁸ m.s⁻¹"),
    (r"$S(t)=\frac{1}{2}at^2+v_0 t+S_0$", "S(t)=(1/2)at²+v₀ t+S₀"),
    (r"$\binom{n}{k} = \frac{n!}{k!(n-k)!}$", "C(n, k) = n!/(k!(n-k)!)"),
    (r"$\sqrt[3]{8} = 2$", "∛8 = 2"),
    (r"\( z = 1 + i\sqrt{3} \) et \[ |z| = 2 \]", "z = 1 + i√3 et |z| = 2"),
    (r"$\{x \in \mathbb{R} \mid x > 0\}$", "{x ∈ ℝ | x > 0}"),
    (r"$\vec{F} = m\vec{a}$", "vecteur F = m vecteur a"),
    (r"x \leq 3 donc \frac{1}{2} < 1", "x ≤ 3 donc 1/2 < 1"),       # commandes sans $
    ("C_xH_yO_z", "CxHyOz"),                                           # inconnues en indice : collees
]


class NotationTests(unittest.TestCase):
    def test_cas(self):
        for source, attendu in CAS:
            self.assertEqual(main.clean_whatsapp_response(source), attendu, source)

    def test_ni_latex_ni_marques_whatsapp(self):
        for source, _ in CAS:
            sortie = main.clean_whatsapp_response(source)
            for interdit in ("\\", "$", "_", "{x", "^{"):
                self.assertNotIn(interdit, sortie.replace("{x ∈", ""), source)

    def test_texte_normal_intact(self):
        for texte in ["Voici *important* et _attention_ : relis l'énoncé.", "Le prix est 2 000 F.",
                      "Écris à contact@afrjigi.com ou va sur https://wa.me/13154030671_x"]:
            self.assertEqual(main.clean_whatsapp_response(texte), texte)


if __name__ == "__main__":
    unittest.main()

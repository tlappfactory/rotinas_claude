#!/usr/bin/env python3
"""calendario.py — dias em que não se espera edição ordinária do DOU.

Fim de semana + feriados nacionais (fixos e móveis). Ponto facultativo
(ex.: Dia do Servidor, 28/10) NÃO entra: o DOU circula normalmente.

Uso:  python scripts/calendario.py 2026-11-02   # imprime o motivo e sai 0 se
                                                # não há edição esperada; 1 caso contrário
"""
import sys
from datetime import date, timedelta

FIXOS = {
    (1, 1): "Confraternização Universal", (4, 21): "Tiradentes",
    (5, 1): "Dia do Trabalho", (9, 7): "Independência", (10, 12): "N. Sra. Aparecida",
    (11, 2): "Finados", (11, 15): "Proclamação da República",
    (11, 20): "Consciência Negra", (12, 25): "Natal",
}


def pascoa(ano: int) -> date:
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def motivo_sem_edicao(d: date) -> str | None:
    """Retorna o motivo (str) se não se espera edição ordinária; senão None."""
    if d.weekday() >= 5:
        return "fim de semana"
    if (d.month, d.day) in FIXOS:
        return f"feriado nacional ({FIXOS[(d.month, d.day)]})"
    p = pascoa(d.year)
    moveis = {p - timedelta(days=48): "Carnaval (segunda)", p - timedelta(days=47): "Carnaval (terça)",
              p - timedelta(days=2): "Sexta-feira Santa", p + timedelta(days=60): "Corpus Christi"}
    if d in moveis:
        return f"feriado nacional ({moveis[d]})"
    return None


if __name__ == "__main__":
    m = motivo_sem_edicao(date.fromisoformat(sys.argv[1]))
    if m:
        print(m)
        sys.exit(0)
    sys.exit(1)

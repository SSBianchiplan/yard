"""Executor de script SQL para as migrations.

asyncpg não aceita múltiplos comandos num statement preparado, então cada comando vai
sozinho — e o SQL das migrations continua legível como um bloco único.
"""

from alembic import op


def split(script: str) -> list[str]:
    """Divide por `;`, ignorando os que estão dentro de `$$`, de string ou de comentário.

    Sim, comentário importa: `-- captura só vale; exceção é manual` tem um ponto e vírgula
    que não termina comando nenhum.
    """
    statements: list[str] = []
    buffer: list[str] = []
    in_dollar = False
    in_line_comment = False
    in_block_comment = False
    in_string = False
    index = 0

    while index < len(script):
        char = script[index]
        pair = script[index : index + 2]

        if in_line_comment:
            buffer.append(char)
            if char == "\n":
                in_line_comment = False
            index += 1
            continue

        if in_block_comment:
            buffer.append(char)
            if pair == "*/":
                buffer.append(script[index + 1])
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue

        if in_string:
            buffer.append(char)
            if char == "'":
                in_string = False
            index += 1
            continue

        if pair == "$$":
            in_dollar = not in_dollar
            buffer.append("$$")
            index += 2
            continue

        if not in_dollar and pair == "--":
            in_line_comment = True
            buffer.append(pair)
            index += 2
            continue

        if not in_dollar and pair == "/*":
            in_block_comment = True
            buffer.append(pair)
            index += 2
            continue

        if char == "'":
            in_string = True
            buffer.append(char)
            index += 1
            continue

        if char == ";" and not in_dollar:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
            continue

        buffer.append(char)
        index += 1

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _is_only_comments(statement: str) -> bool:
    """Comentário solto entre comandos não é comando — executá-lo é erro de sintaxe."""
    return all(
        not line.strip() or line.strip().startswith("--") for line in statement.splitlines()
    )


def exec_script(script: str) -> None:
    for statement in split(script):
        if _is_only_comments(statement):
            continue
        op.execute(statement)

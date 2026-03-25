# 🛠 Forster Tools

Conjunto de ferramentas de automação para agências de conteúdo e produtoras de vídeo. Desenvolvido pela [Forster Filmes](https://github.com/forsterfilmes) para eliminar tarefas manuais repetitivas e ganhar tempo para o que importa: criar.

Cada ferramenta é independente, documentada e pronta para uso com configuração mínima.

---

## Ferramentas

| Ferramenta | O que faz |
|---|---|
| [💸 lembretes](https://github.com/forsterfilmes/forster-lembretes) | Lembretes automáticos de pagamento via WhatsApp — app desktop com interface gráfica |
| [🎙 auphonic](./auphonic/) | Extrai áudio de MP4s e processa automaticamente no Auphonic |
| [🧾 notas-fiscais](./notas-fiscais/) | Organiza XMLs de NFS-e e lança no arquivo de controle mensal |

---

## Filosofia

> **Fricção zero.** Cada ferramenta foi desenhada para ser instalada uma vez e esquecida. O objetivo é que o usuário não precise pensar em tecnologia — só nos resultados.

---

## Instalação

Cada ferramenta tem seu próprio `README.md` com instruções específicas. Em geral:

```bash
# Clone o repositório
git clone https://github.com/forsterfilmes/forster-tools.git ~/Documents/forster-tools

# Entre na ferramenta desejada e configure
cd ~/Documents/forster-tools/auphonic
cp config.exemplo.json config.json
# edite config.json com suas credenciais
```

---

## Roadmap

- [ ] Interface gráfica unificada (Electron) para todas as ferramentas
- [ ] Suporte a Windows
- [ ] Instalador único com wizard de configuração

---

## Licença

MIT — use, adapte e distribua livremente.

---

Feito com ☕ por [Forster Filmes](https://github.com/forsterfilmes)

# 📋 xbar-fila-edicao

Plugin de [Xbar](https://xbarapp.com) que mostra no menu bar o próximo Reel/vídeo
pendente de edição da Forster, cruzando dois tipos de fonte:

- **Detecção automática**: gerada pelo script `fila_de_edicao.py` (repo
  [`forster-aprovacoes`](https://github.com/oiforster/forster-aprovacoes)), que compara
  o Conteúdo Mensal de cada cliente recorrente com os vídeos já entregues em
  `06_Entregas/` e escreve um bloco automático na `Fila de Edição.md`
- **Tabelas manuais**: itens que a Silvana digita direto no calendário da mesma
  `Fila de Edição.md`, pra pedidos extras/urgentes fora do plano

Itens atrasados aparecem em vermelho. Cada item tem um submenu "✅ Já entreguei" que
marca a pendência como resolvida na hora (grava numa lista local, sem precisar do NAS
nem esperar o cron do dia seguinte).

## Instalação

Copiar (não usar symlink) para a pasta de plugins do Xbar em cada Mac:

```bash
cp fila-de-edicao.1m.py "$HOME/Library/Application Support/xbar/plugins/"
```

Precisa do script `fila_de_edicao.py` presente em
`~/Documents/forster-aprovacoes/scripts/` (mesmo Mac) para o botão "Já entreguei" e
para o cron diário funcionarem — ver o README desse repo.

## Sincronização de versões

Esse arquivo existe solto em dois Macs (Samuel e Silvana), fora do Syncthing. Depois
de editar aqui, copiar por cima das duas cópias instaladas:

- `~/Library/Application Support/xbar/plugins/fila-de-edicao.1m.py` (Mac do Samuel)
- `~/Library/Application Support/xbar/plugins/fila-de-edicao.1m.py` (Mac da Silvana,
  via SSH `silvanaforster@MacBook-Air-de-Silvana.local`)

Depois fazer commit e push aqui.

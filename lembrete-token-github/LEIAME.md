# Lembrete do token do GitHub

Avisa quando o token que grava as aprovações dos clientes estiver perto de vencer.

## Por que existe

A página de aprovação grava o estado do cliente pela Pages Function do Cloudflare
(`functions/api/estado.js` no repositório `forster-aprovacoes`), que usa o secret
`GH_TOKEN`. Esse token é um PAT fine-grained do GitHub e **vence em 18/07/2027**.

Se vencer sem troca, o cliente clica em aprovar, vê a confirmação na tela e nada é
gravado. Nenhum erro aparece. É o mesmo tipo de falha silenciosa que a remediação de
18/07/2026 resolveu, e este lembrete existe para o vencimento não recriá-la.

## Como funciona

O launchd roda o script no dia 1 de cada mês, às 10h. Antes de 01/06/2027 ele sai em
silêncio e só anota no `lembrete.log`. A partir dessa data, abre um alerta crítico com
o passo a passo da renovação, e repete todo mês até alguém desligar o agendamento.

## Instalar em outra máquina

```bash
cp ~/Documents/forster-tools/lembrete-token-github/com.forster.lembrete-token-github.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forster.lembrete-token-github.plist
```

O caminho do script dentro do plist é absoluto (exigência do launchd) e assume o
usuário `samuelforster`. Ajustar se instalar em outra conta.

## Desligar depois de renovar o token

```bash
launchctl bootout gui/$(id -u)/com.forster.lembrete-token-github
rm ~/Library/LaunchAgents/com.forster.lembrete-token-github.plist
```

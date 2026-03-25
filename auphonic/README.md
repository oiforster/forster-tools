# 🎙 Auphonic Automator

Automatiza o tratamento de áudio de gravações de vídeo usando a API do Auphonic. Extrai o áudio dos MP4s, envia para o Auphonic, monitora o processamento e baixa os arquivos tratados — tudo com um único comando.

---

## O que faz

1. Localiza todos os MP4s na pasta do projeto
2. Extrai o áudio em WAV (24-bit) mantendo a estrutura de subpastas
3. Envia cada arquivo para o Auphonic com um preset configurável
4. Monitora o processamento em tempo real
5. Baixa os arquivos tratados na pasta correta

---

## Configuração

**1. Copie o arquivo de exemplo:**
```bash
cp config.exemplo.json config.json
```

**2. Preencha com suas credenciais:**
```json
{
  "api_user": "seu-email@auphonic.com",
  "api_pass": "sua-senha",
  "preset":   "ID-do-preset"
}
```

Para encontrar o ID do preset: acesse [auphonic.com/presets](https://auphonic.com/presets) e copie o identificador da URL.

---

## Uso

```bash
bash auphonic.sh
```

O script pedirá o caminho da pasta do projeto e confirmará os arquivos encontrados antes de processar.

---

## Estrutura esperada do projeto

```
Pasta do Projeto/
├── 1. Sony A7III - Slog2 (S-Gamut)/   ← onde estão os MP4s
│   ├── A001.mp4
│   └── subpasta/
│       └── A002.mp4
├── Áudios para tratar/                 ← criado pelo script
└── 7. Áudios Tratados/                 ← criado pelo script
```

---

## Requisitos

- macOS (zsh)
- `ffmpeg` instalado: `brew install ffmpeg`
- Conta no [Auphonic](https://auphonic.com) com pelo menos um preset criado

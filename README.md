---
title: StudioPrompter Processamento
emoji: 🎙️
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# StudioPrompter: serviço de processamento

Faz duas coisas para a tela **Revisão** do app:

- **Voz limpa:** DeepFilterNet 3 (código aberto) nos modos Suave, Padrão e Forte, mais voz realçada e
  volume nivelado, em AAC 48 kHz.
- **Vídeo final:** filtro de estúdio, recorte real de 4:5 e 1:1 e a voz limpa, com ffmpeg.

O backend (Worker) decide quem pode usar e assina um token por vídeo. Este serviço só aceita pedidos com
esse token (`STUDIO_PROCESSING_SECRET`, o mesmo segredo dos dois lados). Os arquivos são apagados assim
que o app baixa o vídeo final e, em qualquer caso, em até 1 hora.

## Publicar no Hugging Face Spaces (grátis)

1. **Crie a conta** em https://huggingface.co/join.
2. **Crie o Space:** https://huggingface.co/new-space
   - Nome: `studioprompter` (ou outro).
   - **SDK: Docker** → Blank.
   - Hardware: **CPU basic (free)**.
   - Visibilidade: **Public**, para o app conseguir acessar. Os pedidos continuam protegidos pelo token.
3. **Gere o segredo** no PC, na raiz do projeto, e guarde o valor:
   ```bash
   node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
   ```
4. **Cadastre o segredo no Space:** Settings → *Variables and secrets* → **New secret**
   - Nome: `STUDIO_PROCESSING_SECRET`.
   - Valor: o que você gerou.
5. **Envie os arquivos desta pasta** (`processing/`) para o Space. Escolha **um** dos dois jeitos:
   - Pelo site: aba *Files* → *Add file* → *Upload files*. Envie `Dockerfile`, `README.md`,
     `requirements.txt`, `.dockerignore` e a pasta `app/` inteira.
   - Pelo git:
     ```bash
     git clone https://huggingface.co/spaces/SEU-USUARIO/studioprompter
     # copie o conteúdo de processing/ para dentro da pasta clonada, depois:
     git add . && git commit -m "serviço de processamento" && git push
     ```
6. **Aguarde a construção.** Na 1ª vez demora uns 10 minutos (baixa o PyTorch e o modelo). Quando ficar
   *Running*, abra `https://SEU-USUARIO-studioprompter.hf.space/`: deve mostrar `{"status":"ok"}`.

## Ligar ao backend

No `backend/.env`:

```bash
# STUDIO_MODE=mock          ← comente esta linha para usar o servidor de verdade
STUDIO_PROCESSING_URL=https://SEU-USUARIO-studioprompter.hf.space
STUDIO_PROCESSING_SECRET=o-mesmo-valor-cadastrado-no-space
```

Reinicie o backend (`npm run dev`). No Worker publicado, use:

```bash
wrangler secret put STUDIO_PROCESSING_URL
wrangler secret put STUDIO_PROCESSING_SECRET
```

## Testes (no PC, sem o modelo nem o ffmpeg)

```bash
cd processing
python -m unittest discover -s tests -t .
```

## Observações

- **Velocidade (CPU grátis):** para 2 min de vídeo, estimo 30–60 s para limpar a voz e 1–3 min para o
  vídeo final. O serviço processa um vídeo por vez.
- **O Space dorme** depois de um tempo sem uso. O 1º vídeo depois disso demora mais, enquanto ele acorda.
- **Os efeitos** são LUTs 3D em `app/luts/*.cube`, os mesmos de `assets/luts/` do app. Gere ou atualize
  com `python processing/tools/luts.py` (na raiz do projeto). Ele também copia `filters.json`. Depois
  publique o Space de novo. Para usar LUTs reais de cinema, veja `assets/luts/README.md`.

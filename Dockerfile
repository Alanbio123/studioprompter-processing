# Hugging Face Space (Docker, CPU grátis). Voz limpa com DeepFilterNet 3 + vídeo final com ffmpeg.
FROM python:3.10-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Usuário sem privilégios (padrão dos Spaces).
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /home/user/app

# PyTorch só de CPU (menor) antes do DeepFilterNet. torchaudio < 2.1: o deepfilternet 0.5.6
# ainda importa torchaudio.backend (removido na 2.1).
RUN pip install --no-cache-dir --user torch==2.0.1 torchaudio==2.0.2 \
      --index-url https://download.pytorch.org/whl/cpu
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user app ./app
# Baixa o modelo DeepFilterNet3 na construção (o 1º vídeo não espera o download).
RUN python -c "from df.enhance import init_df; init_df()"

EXPOSE 7860
# Render (e outros) informam a porta em $PORT; sem ela (Hugging Face), 7860.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]

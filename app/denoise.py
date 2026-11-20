"""DeepFilterNet 3 num processo à parte: ao terminar, a memória do PyTorch volta ao sistema
(o Render grátis tem 512 MB, e o vídeo final roda depois no mesmo servidor).

Uso: python app/denoise.py <entrada.wav> <saída.wav> <limite em dB | none>
"""

import sys


def main(raw: str, output: str, limit: float | None) -> None:
    import torch

    torch.set_num_threads(1)  # menos memória; a CPU grátis é fraca de qualquer jeito
    from df.enhance import enhance, init_df, load_audio, save_audio

    model, df_state, _ = init_df()
    audio, _ = load_audio(raw, sr=df_state.sr())
    with torch.no_grad():
        enhanced = enhance(model, df_state, audio, atten_lim_db=limit)
    save_audio(output, enhanced, df_state.sr())


if __name__ == '__main__':
    raw_path, output_path, limit_db = sys.argv[1:]
    main(raw_path, output_path, None if limit_db == 'none' else float(limit_db))

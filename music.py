import pygame
import numpy as np
import pyaudio
import threading
import tkinter as tk
from tkinter import filedialog
from pydub import AudioSegment
import sys
import math
import os
import time
from pathlib import Path
from datetime import datetime

# 导入自定义模块（请确保这两个文件存在）
from gfont import get_chinese_font

# ================= 日志配置 =================
LOG_FILE = "music_log.txt"

class DetailedLogger:
    def __init__(self, log_file):
        self.log_file = log_file
        self._write_header()
    
    def _write_header(self):
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write(f"{'='*80}\n")
                f.write(f"音乐频谱播放器详细日志 - 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"{'='*80}\n\n")
        except Exception as e:
            print(f"写入日志头失败: {e}")
    
    def log(self, msg, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] [{level}] {msg}\n"
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(line)
                f.flush()
        except Exception as e:
            print(f"写入日志失败: {e}")
        short_msg = msg[:120] + "..." if len(msg) > 120 else msg
        print(f"[{timestamp}] [{level}] {short_msg}")

logger = DetailedLogger(LOG_FILE)

# ================= 音频参数配置 =================
CHUNK = 2048
FORMAT = pyaudio.paInt16
CHANNELS = 2          # 双声道
RATE = 44100
SMOOTHING = 0.4
BARS = 64
LOGICAL_WIDTH = 1200
LOGICAL_HEIGHT = 700
# ==============================================

class MusicPlayer:
    def __init__(self):
        logger.log(f"初始化 MusicPlayer | pygame_version={pygame.version.ver} | python={sys.version.split()[0]}")
        pygame.init()
        self.logical_width = LOGICAL_WIDTH
        self.logical_height = LOGICAL_HEIGHT
        self.is_fullscreen = False
        self.scale_x = 1.0
        self.scale_y = 1.0
        self._update_display_mode()
        
        self.clock = pygame.time.Clock()
        logger.log(f"窗口创建 | 逻辑尺寸={self.logical_width}x{self.logical_height} | 全屏={self.is_fullscreen}")

        # 字体
        self.font = get_chinese_font(24)
        self.small_font = get_chinese_font(18)
        self.freq_font = pygame.font.SysFont("Arial", 12)
        self.val_font = pygame.font.SysFont("Arial", 10)
        self.list_font = get_chinese_font(14)   # 文件夹/文件列表使用中文字体

        # 音频数据
        self.audio_data = None          # 一维 int16 数组，交错立体声 (LRLR...)
        self.data_index = 0             # 当前播放帧索引（不是声道数）
        self.playing = False
        self.lock = threading.Lock()

        # 频谱数据
        self.spectrum = None
        self.freq_band_indices = None
        self.band_center_freqs = None
        self.freq_labels = None
        self.BARS = BARS
        self._generate_freq_bands()

        # 参考频段 21-45Hz
        self.scale_band_indices = [i for i, f in enumerate(self.band_center_freqs) if 21 <= f <= 169]
        if self.scale_band_indices:
            freqs_str = [f"{self.band_center_freqs[i]:.1f}" for i in self.scale_band_indices]
            logger.log(f"自动缩放参考频段 | count={len(self.scale_band_indices)} | freqs={freqs_str}")

        # 波形数据（立体声）
        self.waveform_stereo = np.zeros((CHUNK, 2), dtype=np.float32)

        # UI 参数
        self.threshold = 0.25
        self.threshold_step = 0.02
        self.base_max_height = 350

        self.auto_zoom_enabled = False
        self.zoom_factor = 1.0
        self.loop_mode = 2   # 0=顺序,1=单曲,2=列表循环

        # PyAudio
        self.p = pyaudio.PyAudio()
        self.stream = None
        self._init_audio_stream()

        self.current_filename = ""
        self.temp_surface = pygame.Surface((self.logical_width, self.logical_height))

        # 文件浏览器
        self.current_browse_dir = os.getcwd()
        self.folder_list = []          # 文件夹路径或 ".."
        self.playlist = []             # 音乐文件绝对路径
        self.current_playlist_index = -1
        self.folder_scroll = 0
        self.file_scroll = 0
        self.max_folder_display = 8
        self.max_file_display = 12
        self._scan_current_directory()

        # 时间相关
        self.current_time = 0.0
        self.total_time = 0.0

        # 进度条逻辑矩形（逻辑坐标）
        self.progress_bar_rect = pygame.Rect(300, 120, 400, 18)

        # 加载动画
        self.loading = False
        self.loading_anim_start = 0.0
        self.loading_anim_speed = 1.0

        # 列表循环请求
        self.request_next_track = False

        # 自动缩放平滑变量
        self.old_target_room = 1.0

        # 右侧面板区域（逻辑坐标）
        self.right_panel_rect = pygame.Rect(LOGICAL_WIDTH - 250, 80, 230, 500)

        logger.log("MusicPlayer 初始化完成")

    def _update_display_mode(self):
        """根据全屏标志更新显示模式"""
        if self.is_fullscreen:
            info = pygame.display.Info()
            self.window_width, self.window_height = info.current_w, info.current_h
            self.screen = pygame.display.set_mode((self.window_width, self.window_height), pygame.FULLSCREEN)
        else:
            self.window_width, self.window_height = self.logical_width, self.logical_height
            self.screen = pygame.display.set_mode((self.window_width, self.window_height))
        self.scale_x = self.window_width / self.logical_width
        self.scale_y = self.window_height / self.logical_height
        pygame.display.set_caption("音乐频谱播放器 - 双声道/文件浏览器")
        logger.log(f"显示模式更新 | 窗口尺寸={self.window_width}x{self.window_height} | 缩放比例=({self.scale_x:.2f},{self.scale_y:.2f})")

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        self._update_display_mode()
        # 重新绘制临时表面（下一帧自动处理）

    # ---------- 文件浏览器 ----------
    def _scan_current_directory(self):
        try:
            path = Path(self.current_browse_dir)
            # 文件夹列表：返回上级 + 子文件夹
            folders = []
            if self.current_browse_dir != os.path.dirname(self.current_browse_dir):
                folders.append("..")
            for f in path.iterdir():
                if f.is_dir() and not f.name.startswith('.'):
                    folders.append(str(f.absolute()))
            self.folder_list = folders
            # 音乐文件
            supported_ext = ('.mp3', '.wav', '.ogg', '.flac', '.m4a')
            self.playlist = [str(f.absolute()) for f in path.iterdir() if f.is_file() and f.suffix.lower() in supported_ext]
            self.playlist.sort()
            logger.log(f"扫描目录: {self.current_browse_dir} | 文件夹数={len(self.folder_list)} | 音乐文件数={len(self.playlist)}")
        except Exception as e:
            logger.log(f"扫描目录失败: {e}", "ERROR")
            self.folder_list = []
            self.playlist = []

        # 重置滚动
        self.folder_scroll = 0
        self.file_scroll = 0

        # 更新当前播放文件索引
        if self.current_filename and self.current_filename in self.playlist:
            self.current_playlist_index = self.playlist.index(self.current_filename)
        else:
            self.current_playlist_index = -1

    def change_directory(self, target):
        if target == "..":
            parent = os.path.dirname(self.current_browse_dir)
            if parent != self.current_browse_dir:
                self.current_browse_dir = parent
                self._scan_current_directory()
        else:
            self.current_browse_dir = target
            self._scan_current_directory()
        self.stop()
        self.current_filename = ""
        self.current_playlist_index = -1
        logger.log(f"目录切换: {self.current_browse_dir}")

    def load_playlist_item(self, index):
        if 0 <= index < len(self.playlist):
            self.stop()
            self.load_file(self.playlist[index])
            self.current_playlist_index = index

    # ---------- 音频基础 ----------
    def _generate_freq_bands(self):
        min_freq = 20.0
        max_freq = RATE / 2
        band_edges = np.logspace(np.log10(min_freq), np.log10(max_freq), self.BARS + 1)
        self.band_center_freqs = [math.sqrt(band_edges[i] * band_edges[i+1]) for i in range(self.BARS)]
        self.spectrum = np.zeros(self.BARS, dtype=np.float32)

        bin_width = RATE / CHUNK
        fft_len = CHUNK // 2 + 1
        freq_bins = np.linspace(0, RATE/2, fft_len)

        indices = []
        for i in range(self.BARS):
            start_f = band_edges[i]
            end_f = band_edges[i+1]
            idx_start = np.searchsorted(freq_bins, start_f)
            idx_end = np.searchsorted(freq_bins, end_f, side='right')
            if idx_start == 0:
                idx_start = 1
            if idx_start == idx_end:
                idx_end = min(idx_start + 1, fft_len)
            indices.append((idx_start, idx_end))
        self.freq_band_indices = indices
        self._render_freq_labels()

    def _render_freq_labels(self):
        self.freq_labels = []
        for freq in self.band_center_freqs:
            if freq >= 1000:
                text = f"{freq/1000:.1f}k"
            else:
                text = f"{freq:.0f}"
            surf = self.freq_font.render(text, True, (220, 220, 180))
            rotated = pygame.transform.rotate(surf, -45)
            self.freq_labels.append(rotated)

    def _init_audio_stream(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        try:
            self.stream = self.p.open(format=FORMAT,
                                      channels=CHANNELS,
                                      rate=RATE,
                                      output=True,
                                      frames_per_buffer=CHUNK,
                                      stream_callback=self._audio_callback)
            self.stream.start_stream()
            logger.log("音频流打开成功")
        except Exception as e:
            logger.log(f"音频流打开失败: {e}", "ERROR")
            self.stream = None

    def _audio_callback(self, in_data, frame_count, time_info, status):
        with self.lock:
            if self.playing and self.audio_data is not None:
                start = self.data_index * CHANNELS   # 转换为声道索引
                end = start + frame_count * CHANNELS
                total_len = len(self.audio_data)
                if end <= total_len:
                    data = self.audio_data[start:end]
                    self.data_index += frame_count
                else:
                    data = self.audio_data[start:]
                    self.data_index = total_len // CHANNELS
                    self.playing = False
                    # 循环处理
                    if self.loop_mode == 1:      # 单曲循环
                        self.data_index = 0
                        self.current_time = 0.0
                        self.playing = True
                        start = 0
                        end = start + frame_count * CHANNELS
                        if end <= total_len:
                            data = self.audio_data[start:end]
                            self.data_index = frame_count
                        else:
                            data = self.audio_data[start:]
                            self.data_index = total_len // CHANNELS
                            silence = np.zeros(frame_count * CHANNELS - len(data), dtype=np.int16)
                            data = np.concatenate((data, silence))
                    elif self.loop_mode == 2:    # 列表循环
                        self.request_next_track = True
                        silence = np.zeros(frame_count * CHANNELS - len(data), dtype=np.int16)
                        data = np.concatenate((data, silence))
                    else:                        # 顺序播放
                        silence = np.zeros(frame_count * CHANNELS - len(data), dtype=np.int16)
                        data = np.concatenate((data, silence))

                try:
                    # 计算频谱（基于单声道平均值）
                    self._compute_spectrum(data)
                    # 更新立体波形数据
                    wave = data.astype(np.float32) / 32768.0
                    if CHANNELS == 2:
                        wave_reshaped = wave.reshape(-1, 2)
                        # 只保留最近 CHUNK 帧（实际 data 长度就是 frame_count * 2）
                        self.waveform_stereo = wave_reshaped[-CHUNK:] if wave_reshaped.shape[0] >= CHUNK else wave_reshaped
                    else:
                        # 单声道兼容
                        self.waveform_stereo = np.column_stack((wave, wave))[-CHUNK:]
                except Exception as e:
                    logger.log(f"频谱计算错误: {e}", "ERROR")

                out_data = data.tobytes()
            else:
                out_data = np.zeros(frame_count * CHANNELS, dtype=np.int16).tobytes()
        return (out_data, pyaudio.paContinue)

    def _compute_spectrum(self, data):
        """data: 一维 int16 数组，交错立体声，长度 = frame_count * CHANNELS"""
        # 转为 float32 并归一化
        samples = data.astype(np.float32) / 32768.0
        # 转为双声道矩阵 (帧数, 2)
        if CHANNELS == 2:
            samples = samples.reshape(-1, 2)
            mono = np.mean(samples, axis=1)
        else:
            mono = samples
        # 去直流
        mono = mono - np.mean(mono)
        # 加窗
        window = np.hanning(len(mono))
        windowed = mono * window
        # FFT (自定义 C++ 扩展)
        fft_vals = np.fft.rfft(windowed.astype(np.float64))
        magnitude = np.abs(fft_vals)

        raw_band_vals = []
        for idx_start, idx_end in self.freq_band_indices:
            band_mag = np.mean(magnitude[idx_start:idx_end])
            db = 20.0 * math.log10(band_mag + 1e-6)
            norm = (db + 20.0) / 80.0
            norm = np.clip(norm, 0.0, 1.0)
            raw_band_vals.append(norm)

        # 平滑
        self.spectrum = self.spectrum * SMOOTHING + np.array(raw_band_vals) * (1 - SMOOTHING)

        # 更新时间
        if self.audio_data is not None:
            self.current_time = self.data_index / RATE

        # 自动缩放
        if self.auto_zoom_enabled and self.scale_band_indices:
            raw_avg_vol = np.mean([raw_band_vals[i] for i in self.scale_band_indices])
            target_zoom = 0.7 + raw_avg_vol / 1.5
            target_zoom = (target_zoom - self.old_target_room) * 0.2 + self.old_target_room
            target_zoom = max(1.0, min(1.5, target_zoom))
            self.old_target_room = target_zoom
            #logger.log("缩放大小：" + str(target_zoom))
            self.zoom_factor = target_zoom
        else:
            self.zoom_factor = 1.0

    def load_file(self, filepath):
        logger.log(f"开始加载: {filepath}")
        self.loading = True
        self.loading_anim_start = time.time()
        try:
            audio = AudioSegment.from_file(filepath)
            # 转为双声道、目标采样率
            audio = audio.set_channels(CHANNELS).set_frame_rate(RATE).set_sample_width(2)
            samples = np.array(audio.get_array_of_samples(), dtype=np.int16)
            if len(samples) == 0:
                logger.log("音频无数据", "ERROR")
                return False
            with self.lock:
                self.audio_data = samples
                self.data_index = 0
                self.playing = False
            self.current_filename = filepath
            self.spectrum = np.zeros(self.BARS, dtype=np.float32)
            self.total_time = len(samples) / CHANNELS / RATE
            self.current_time = 0.0
            self.zoom_factor = 1.0
            logger.log(f"加载成功 | 时长={self.total_time:.2f}s | 总采样帧数={len(samples)//CHANNELS}")
            return True
        except Exception as e:
            logger.log(f"加载失败: {e}", "ERROR")
            return False
        finally:
            self.loading = False

    def play(self):
        if self.audio_data is not None:
            with self.lock:
                if self.data_index >= len(self.audio_data) // CHANNELS:
                    self.data_index = 0
                self.playing = True

    def pause(self):
        with self.lock:
            self.playing = False

    def stop(self):
        with self.lock:
            self.playing = False
            self.data_index = 0
            self.current_time = 0.0

    def toggle_auto_zoom(self):
        self.auto_zoom_enabled = not self.auto_zoom_enabled
        logger.log("G按下:" + str(self.auto_zoom_enabled))
        if not self.auto_zoom_enabled:
            self.zoom_factor = 1.0

    def toggle_loop_mode(self):
        self.loop_mode = (self.loop_mode + 1) % 3

    def next_track(self):
        if self.playlist:
            new_idx = (self.current_playlist_index + 1) % len(self.playlist)
            self.stop()
            self.load_file(self.playlist[new_idx])
            self.current_playlist_index = new_idx

    def prev_track(self):
        if self.playlist:
            new_idx = (self.current_playlist_index - 1) % len(self.playlist)
            self.stop()
            self.load_file(self.playlist[new_idx])
            self.current_playlist_index = new_idx

    def seek_to_position(self, logical_x):
        if self.auto_zoom_enabled:
            return
        if self.audio_data is None:
            return
        bar_rect = self.progress_bar_rect
        if logical_x < bar_rect.x:
            logical_x = bar_rect.x
        elif logical_x > bar_rect.x + bar_rect.width:
            logical_x = bar_rect.x + bar_rect.width
        ratio = (logical_x - bar_rect.x) / bar_rect.width
        total_frames = len(self.audio_data) // CHANNELS
        new_index = int(ratio * total_frames)
        with self.lock:
            self.data_index = new_index
            self.current_time = new_index / RATE

    def _format_time(self, seconds):
        if seconds is None or math.isnan(seconds):
            return "00:00"
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"

    # ---------- 绘制界面 ----------
    def _draw_spectrum(self, surface):
        w = surface.get_width()
        bar_width = w // self.BARS
        base_y = int(500 * self.scale_y)
        max_height = int(self.base_max_height * self.scale_y)
        x = 0
        for i, val in enumerate(self.spectrum):
            if val > self.threshold:
                new_val = val - self.threshold
                height = int(new_val * max_height)
                if height < 2:
                    height = 2
                a = int(255 * val)
                color = (a, 255 - a, 0)
                pygame.draw.rect(surface, color, (x, base_y - height, bar_width - 1, height))
                pygame.draw.line(surface, (255,255,255), (x, base_y - height), (x + bar_width - 1, base_y - height), 1)
                val_text = f"{val:.2f}"
                if height > 20:
                    text_surf = self.val_font.render(val_text, True, (255,255,255))
                    text_x = x + bar_width//2 - text_surf.get_width()//2
                    text_y = base_y - height + 3
                    surface.blit(text_surf, (text_x, text_y))
                else:
                    text_surf = self.val_font.render(val_text, True, (255,255,200))
                    text_x = x + bar_width//2 - text_surf.get_width()//2
                    text_y = base_y - height - 12
                    surface.blit(text_surf, (text_x, text_y))
            label_surf = self.freq_labels[i]
            label_x = x + bar_width//2 - label_surf.get_width()//2
            label_y = base_y + int(5 * self.scale_y)
            surface.blit(label_surf, (label_x, label_y))
            x += bar_width
        pygame.draw.line(surface, (100,100,100), (0, base_y), (w, base_y), 2)
        threshold_y = base_y - int(self.threshold * max_height)
        for x_start in range(0, w, 10):
            pygame.draw.line(surface, (255,50,50), (x_start, threshold_y), (x_start+6, threshold_y), 2)
        th_text = self.small_font.render(f"阈值: {self.threshold:.2f} (↑/↓)", True, (255,180,100))
        surface.blit(th_text, (int((self.logical_width - 200) * self.scale_x), threshold_y - 25))

    def _draw_waveform(self, surface):
        wave_y = int(590 * self.scale_y)
        wave_h = int(80 * self.scale_y)
        mid_y = wave_y + wave_h // 2
        w = surface.get_width()
        step = w / CHUNK

        pygame.draw.rect(surface, (30,30,50), (0, wave_y, w, wave_h))
        pygame.draw.line(surface, (80,80,120), (0, mid_y), (w, mid_y), 1)

        if self.waveform_stereo is not None and self.waveform_stereo.shape[0] == CHUNK:
            points_left = []
            points_right = []
            for i in range(CHUNK):
                x = int(i * step)
                left_val = self.waveform_stereo[i, 0]
                right_val = self.waveform_stereo[i, 1]
                y_left = mid_y - int(left_val * (wave_h / 2))
                y_right = mid_y - int(right_val * (wave_h / 2))
                points_left.append((x, y_left))
                points_right.append((x, y_right))
            if len(points_left) > 1:
                pygame.draw.lines(surface, (100,150,255), False, points_left, 2)
                pygame.draw.lines(surface, (255,150,100), False, points_right, 2)
        else:
            # 兼容旧版
            if hasattr(self, 'waveform_data') and len(self.waveform_data) == CHUNK:
                points = []
                for i in range(CHUNK):
                    x = int(i * step)
                    y = mid_y - int(self.waveform_data[i] * (wave_h / 2))
                    points.append((x, y))
                if len(points) > 1:
                    pygame.draw.lines(surface, (100,200,255), False, points, 2)

        label = self.small_font.render("立体声波形 (蓝:左声道 橙:右声道)", True, (180,180,200))
        surface.blit(label, (int(10*self.scale_x), wave_y + 5))

    def _draw_ui(self, surface):
        surface.fill((20,20,40))
        # 标题
        title = self.font.render("音乐频谱播放器", True, (220,220,255))
        surface.blit(title, (int(20*self.scale_x), int(20*self.scale_y)))
        # 播放状态
        status = "▶ 播放中" if self.playing else "⏸ 暂停/停止"
        status_color = (100,255,100) if self.playing else (255,200,100)
        status_surf = self.font.render(status, True, status_color)
        surface.blit(status_surf, (int(20*self.scale_x), int(70*self.scale_y)))

        # 进度条区域（逻辑坐标）
        bar_x_logic = 300
        bar_y_logic = 120
        bar_w_logic = 400
        bar_h_logic = 18
        bar_x = int(bar_x_logic * self.scale_x)
        bar_y = int(bar_y_logic * self.scale_y)
        bar_w = int(bar_w_logic * self.scale_x)
        bar_h = int(bar_h_logic * self.scale_y)
        self.progress_bar_rect = pygame.Rect(bar_x_logic, bar_y_logic, bar_w_logic, bar_h_logic)  # 逻辑坐标
        # 曲目名
        if self.current_filename:
            name = os.path.basename(self.current_filename)
            name_surf = self.small_font.render(name, True, (200,200,200))
            surface.blit(name_surf, (bar_x, bar_y - int(22*self.scale_y)))
        elif self.loading:
            name_surf = self.small_font.render("加载中....", True, (180,180,100))
            surface.blit(name_surf, (bar_x, bar_y - int(22*self.scale_y)))
        else:
            name_surf = self.small_font.render("未加载音乐 — 点击右侧文件", True, (180,180,100))
            surface.blit(name_surf, (bar_x, bar_y - int(22*self.scale_y)))
        # 进度条背景
        pygame.draw.rect(surface, (60,60,80), (bar_x, bar_y, bar_w, bar_h))
        if self.loading:
            elapsed = time.time() - self.loading_anim_start
            period = 1.0 / self.loading_anim_speed
            pos = (elapsed % period) / period
            prog = 2*pos if pos < 0.5 else 2-2*pos
            pygame.draw.rect(surface, (200,200,100), (bar_x, bar_y, int(bar_w * prog), bar_h))
        else:
            if self.audio_data is not None and self.total_time > 0:
                prog = self.current_time / self.total_time
                pygame.draw.rect(surface, (100,200,255), (bar_x, bar_y, int(bar_w * prog), bar_h))
        # 时间
        time_text = f"{self._format_time(self.current_time)} / {self._format_time(self.total_time)}"
        time_surf = self.small_font.render(time_text, True, (220,220,220))
        surface.blit(time_surf, (bar_x + bar_w + int(10*self.scale_x), bar_y + int(3*self.scale_y)))
        # 循环模式
        loop_texts = ["顺序", "单曲循环", "列表循环"]
        loop_surf = self.small_font.render(f"循环模式: {loop_texts[self.loop_mode]}  (按 L 切换)", True, (220,180,100))
        surface.blit(loop_surf, (bar_x, bar_y + bar_h + int(5*self.scale_y)))

        # 快捷键提示（逻辑坐标，不缩放文字大小）
        tips = [
            "快捷键:",
            "[P] 播放/暂停",
            "[S] 停止",
            "[↑]/[↓] 调节阈值",
            "[G] 自动缩放",
            "[L] 循环模式",
            "[F11] 全屏切换",
            "Ctrl+↑/↓ 切换歌曲",
            "[ESC] 退出",
            "鼠标点击进度条跳转(非缩放模式)"
        ]
        y = 170
        for tip in tips:
            tip_surf = self.small_font.render(tip, True, (170,170,210))
            surface.blit(tip_surf, (int(20*self.scale_x), int(y*self.scale_y)))
            y += 28

        # ========== 右侧面板（逻辑坐标）==========
        list_x_logic = self.logical_width - 250
        list_y_logic = 80
        list_w_logic = 230
        list_h_logic = 500
        self.right_panel_rect = pygame.Rect(list_x_logic, list_y_logic, list_w_logic, list_h_logic)
        list_x = int(list_x_logic * self.scale_x)
        list_y = int(list_y_logic * self.scale_y)
        list_w = int(list_w_logic * self.scale_x)
        list_h = int(list_h_logic * self.scale_y)
        pygame.draw.rect(surface, (40,40,60), (list_x, list_y, list_w, list_h))

        # 文件夹标题
        folder_title = self.small_font.render("文件夹", True, (220,220,180))
        surface.blit(folder_title, (list_x + int(10*self.scale_x), list_y + int(5*self.scale_y)))

        # 文件夹列表
        folder_start_y_logic = list_y_logic + 25
        folder_start_y = list_y + int(25*self.scale_y)
        self.folder_rects = []
        visible_folders = self.folder_list[self.folder_scroll:self.folder_scroll + self.max_folder_display]
        for i, item in enumerate(visible_folders):
            if item == "..":
                display_name = "🔙 返回上级"
            else:
                display_name = os.path.basename(item)
                if len(display_name) > 18:
                    display_name = display_name[:15] + "..."
            text_surf = self.list_font.render(display_name, True, (200,200,100))
            text_rect = text_surf.get_rect()
            text_x = list_x + int(10*self.scale_x)
            text_y = folder_start_y + i * int(22*self.scale_y)
            surface.blit(text_surf, (text_x, text_y))
            rect = pygame.Rect(list_x_logic + 10, folder_start_y_logic + i * 22, 230-20, 20)
            self.folder_rects.append(rect)

        # 音乐文件标题
        music_title = self.small_font.render("音乐文件", True, (220,220,180))
        surface.blit(music_title, (list_x + int(10*self.scale_x), folder_start_y + self.max_folder_display * int(22*self.scale_y) + int(5*self.scale_y)))

        # 文件列表
        music_start_y_logic = folder_start_y_logic + self.max_folder_display * 22 + 25
        music_start_y = folder_start_y + self.max_folder_display * int(22*self.scale_y) + int(25*self.scale_y)
        self.file_rects = []
        visible_files = self.playlist[self.file_scroll:self.file_scroll + self.max_file_display]
        for i, filepath in enumerate(visible_files):
            file_name = os.path.basename(filepath)
            if len(file_name) > 20:
                file_name = file_name[:17] + "..."
            color = (255,255,200) if (self.current_playlist_index == self.file_scroll + i) else (180,180,200)
            text_surf = self.list_font.render(file_name, True, color)
            surface.blit(text_surf, (list_x + int(10*self.scale_x), music_start_y + i * int(22*self.scale_y)))
            rect = pygame.Rect(list_x_logic + 10, music_start_y_logic + i * 22, 230-20, 20)
            self.file_rects.append(rect)

        # 底部说明
        note = self.small_font.render(f"频率轴: 对数刻度 (20Hz-{int(RATE/2)}Hz) {self.BARS}柱", True, (130,130,180))
        surface.blit(note, (int(20*self.scale_x), int(480*self.scale_y)))
        zoom_status = f"自动缩放: {'ON' if self.auto_zoom_enabled else 'OFF'}  当前缩放: {self.zoom_factor:.2f}x"
        zoom_surf = self.small_font.render(zoom_status, True, (100,255,100) if self.auto_zoom_enabled else (180,180,180))
        surface.blit(zoom_surf, (int(20*self.scale_x), int(510*self.scale_y)))

    # ---------- 主循环 ----------
    def run(self):
        logger.log("进入主循环")
        frame_count = 0
        last_log = time.time()
        while True:
            frame_count += 1
            if frame_count % 300 == 0:
                now = time.time()
                fps = 300 / (now - last_log) if (now - last_log) > 0 else 0
                last_log = now
                logger.log(f"主循环 | fps={fps:.1f} | playing={self.playing} | time={self.current_time:.2f}/{self.total_time:.2f}")

            # 列表循环请求
            if self.request_next_track:
                self.request_next_track = False
                if self.loop_mode == 2 and self.playlist:
                    self.next_track()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._cleanup()
                    return
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self._cleanup()
                        return
                    elif event.key == pygame.K_p:
                        if self.playing:
                            self.pause()
                        else:
                            self.play()
                    elif event.key == pygame.K_s:
                        self.stop()
                    elif event.key == pygame.K_UP:
                        self.threshold = min(1.0, self.threshold + self.threshold_step)
                    elif event.key == pygame.K_DOWN:
                        self.threshold = max(0.0, self.threshold - self.threshold_step)
                    elif event.key == pygame.K_g:
                        self.toggle_auto_zoom()
                    elif event.key == pygame.K_l:
                        self.toggle_loop_mode()
                    elif event.key == pygame.K_F11:
                        self.toggle_fullscreen()
                    if event.mod & pygame.KMOD_CTRL:
                        if event.key == pygame.K_UP:
                            self.prev_track()
                        elif event.key == pygame.K_DOWN:
                            self.next_track()
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    # 将实际鼠标坐标转换为逻辑坐标
                    mouse_x, mouse_y = event.pos
                    logical_x = int(mouse_x / self.scale_x)
                    logical_y = int(mouse_y / self.scale_y)
                    # 文件夹点击
                    for i, rect in enumerate(self.folder_rects):
                        if rect.collidepoint(logical_x, logical_y):
                            item = self.folder_list[self.folder_scroll + i]
                            self.change_directory(item)
                            break
                    # 文件点击
                    for i, rect in enumerate(self.file_rects):
                        if rect.collidepoint(logical_x, logical_y):
                            idx = self.file_scroll + i
                            self.load_playlist_item(idx)
                            break
                    # 进度条跳转
                    if not self.auto_zoom_enabled and self.progress_bar_rect.collidepoint(logical_x, logical_y):
                        self.seek_to_position(logical_x)
                elif event.type == pygame.MOUSEWHEEL:
                    # 滚轮滚动右侧列表
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    logical_x = int(mouse_x / self.scale_x)
                    logical_y = int(mouse_y / self.scale_y)
                    if self.right_panel_rect.collidepoint(logical_x, logical_y):
                        # 判断滚轮区域：Y 坐标小于文件夹区域末尾则滚动文件夹
                        folder_end_y = self.right_panel_rect.y + 25 + self.max_folder_display * 22
                        if logical_y < folder_end_y:
                            # 文件夹区域
                            new_scroll = self.folder_scroll - event.y
                            max_scroll = max(0, len(self.folder_list) - self.max_folder_display)
                            self.folder_scroll = max(0, min(new_scroll, max_scroll))
                        else:
                            # 文件区域
                            new_scroll = self.file_scroll - event.y
                            max_scroll = max(0, len(self.playlist) - self.max_file_display)
                            self.file_scroll = max(0, min(new_scroll, max_scroll))

            # 绘制到临时表面
            self.temp_surface.fill((0,0,0))
            self._draw_ui(self.temp_surface)
            self._draw_spectrum(self.temp_surface)
            self._draw_waveform(self.temp_surface)

            # 应用自动缩放（如果启用）
            if self.auto_zoom_enabled and self.zoom_factor != 1.0:
                scaled_w = int(self.logical_width * self.zoom_factor)
                scaled_h = int(self.logical_height * self.zoom_factor)
                scaled_surface = pygame.transform.scale(self.temp_surface, (scaled_w, scaled_h))
                x = (self.window_width - scaled_w) // 2
                y = (self.window_height - scaled_h) // 2
                self.screen.fill((0, 0, 0))
                self.screen.blit(scaled_surface, (x, y))
            else:
                # 无缩放：直接拉伸至全窗口（或保持居中不拉伸，但为了填满窗口通常拉伸）
                scaled = pygame.transform.scale(self.temp_surface, (self.window_width, self.window_height))
                self.screen.blit(scaled, (0, 0))

            pygame.display.flip()
            self.clock.tick(30)

    def _cleanup(self):
        logger.log("清理资源")
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.p.terminate()
        pygame.quit()
        sys.exit()

if __name__ == "__main__":
    print("="*50)
    print("音乐频谱播放器 - 双声道/文件浏览器/全屏缩放")
    print("日志文件: music_log.txt")
    print("按 F11 全屏，滚轮滚动列表，右键等")
    print("="*50)
    player = MusicPlayer()
    player.run()
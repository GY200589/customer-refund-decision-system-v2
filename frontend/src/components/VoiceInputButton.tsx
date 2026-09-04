import { AudioOutlined, StopOutlined } from '@ant-design/icons'
import { Button, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { transcribeVoice } from '../api'

interface Props {
  onTranscript: (text: string, meta: { provider: string; demo: boolean }) => void | Promise<void>
  disabled?: boolean
  size?: 'small' | 'middle' | 'large'
  showLabel?: boolean
}

export default function VoiceInputButton({ onTranscript, disabled, size = 'middle', showLabel = true }: Props) {
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)

  const releaseStream = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }

  useEffect(() => () => releaseStream(), [])

  const start = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      message.error('当前浏览器不支持录音，请使用最新版 Chrome 或 Edge')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const preferred = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : undefined
      const recorder = new MediaRecorder(stream, preferred ? { mimeType: preferred } : undefined)
      recorderRef.current = recorder
      chunksRef.current = []
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data)
      }
      recorder.onstop = async () => {
        const audio = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        releaseStream()
        setRecording(false)
        if (!audio.size) {
          message.warning('没有录到声音，请重试')
          return
        }
        setTranscribing(true)
        try {
          const result = await transcribeVoice(audio)
          await onTranscript(result.text, { provider: result.provider, demo: result.demo })
          message.success(result.demo ? '已生成演示转写' : '语音已转成文字')
        } catch (error: any) {
          message.error(error.message || '语音识别失败，仍可使用文字输入')
        } finally {
          setTranscribing(false)
        }
      }
      recorder.start()
      setRecording(true)
    } catch {
      releaseStream()
      message.error('无法使用麦克风，请检查浏览器权限')
    }
  }

  const toggle = () => {
    if (recording) recorderRef.current?.stop()
    else void start()
  }

  return (
    <Button
      icon={recording ? <StopOutlined /> : <AudioOutlined />}
      onClick={toggle}
      disabled={disabled || transcribing}
      loading={transcribing}
      danger={recording}
      size={size}
      title={recording ? '停止录音' : '语音输入'}
      aria-label={recording ? '停止录音' : '语音输入'}
    >
      {showLabel ? (recording ? '停止录音' : transcribing ? '识别中' : '语音输入') : null}
    </Button>
  )
}

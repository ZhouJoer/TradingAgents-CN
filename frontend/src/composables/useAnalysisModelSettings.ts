import { ref } from 'vue'
import { configApi } from '@/api/config'

export interface AnalysisModelSettings {
  quickAnalysisModel: string
  deepAnalysisModel: string
}

const sortModelsByNewest = (configs: any[]) => {
  const getTimestamp = (config: any) => {
    const timeValue = config.created_at || config.updated_at
    const timestamp = timeValue ? new Date(timeValue).getTime() : 0
    return Number.isNaN(timestamp) ? 0 : timestamp
  }

  return [...configs].sort((a, b) => getTimestamp(b) - getTimestamp(a))
}

export function useAnalysisModelSettings(
  fallbackQuick = 'qwen-turbo',
  fallbackDeep = 'qwen-max'
) {
  const modelSettings = ref<AnalysisModelSettings>({
    quickAnalysisModel: fallbackQuick,
    deepAnalysisModel: fallbackDeep
  })
  const availableModels = ref<any[]>([])

  const initializeModelSettings = async () => {
    try {
      const defaultModels = await configApi.getDefaultModels()
      modelSettings.value.quickAnalysisModel = defaultModels.quick_analysis_model
      modelSettings.value.deepAnalysisModel = defaultModels.deep_analysis_model

      const llmConfigs = await configApi.getLLMConfigs()
      availableModels.value = sortModelsByNewest(
        llmConfigs.filter((config: any) => config.enabled)
      )
    } catch (error) {
      console.error('加载默认模型配置失败:', error)
      modelSettings.value.quickAnalysisModel = fallbackQuick
      modelSettings.value.deepAnalysisModel = fallbackDeep
    }
  }

  const getModelParameters = () => ({
    quick_analysis_model: modelSettings.value.quickAnalysisModel,
    deep_analysis_model: modelSettings.value.deepAnalysisModel
  })

  return {
    modelSettings,
    availableModels,
    initializeModelSettings,
    getModelParameters
  }
}

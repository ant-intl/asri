import React, { useState, useCallback, useContext } from 'react';
import { Button, Tag, Image, DatePicker, Select, Input } from 'antd';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';
import { LeftOutlined, RightOutlined, CheckOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import styles from './CardRenderer.module.css';

// ------------------------------------------------------------------
// Form Context (for form_mode cards)
// ------------------------------------------------------------------

interface FormContextValue {
  formValues: Record<string, string>;
  setFormValue: (key: string, value: string) => void;
}

const CardFormContext = React.createContext<FormContextValue | null>(null);

// ------------------------------------------------------------------
// Source Context (for scoped message dispatch)
// ------------------------------------------------------------------

/** sourceId：卡片所属窗口标识，undefined 表示全局（Chat 页面） */
const CardSourceContext = React.createContext<string | undefined>(undefined);

/** 统一 dispatch，携带 sourceId 以便接收方过滤 */
function dispatchSendMessage(content: string, sourceId?: string) {
  window.dispatchEvent(
    new CustomEvent('asri:send-message', { detail: { content, sourceId } })
  );
}

// ------------------------------------------------------------------
// Types
// ------------------------------------------------------------------

interface ActionItem {
  appLink?: string;
  appName?: string;
  appIcon?: string;
  [key: string]: unknown;
}

interface ComponentItem {
  type: string;
  props: Record<string, unknown>;
}

interface SlideData {
  components: ComponentItem[];
}

interface GenericCardData {
  layout?: 'carousel' | 'stack';
  theme?: string;
  slides?: SlideData[];
  footer?: { components: ComponentItem[] };
}

interface CardData {
  card_type: string;
  data?: {
    appHandleText?: string;
    appHandleDataResult?: ActionItem[];
  } & GenericCardData & Record<string, unknown>;
  [key: string]: unknown;
}

interface CardRendererProps {
  card: CardData;
  sourceId?: string;  // 卡片所属窗口标识，用于 Playground 多窗口隔离
}

// ------------------------------------------------------------------
// Generic Component Renderers
// ------------------------------------------------------------------

const THEME_STYLES: Record<string, { color: string; icon: string }> = {
  hotel: { color: '#e8590c', icon: '🏨' },
  train: { color: '#1971c2', icon: '🚄' },
};

const HeaderComponent: React.FC<{ title: string; subtitle?: string; theme?: string }> = ({ title, subtitle, theme }) => {
  const t = theme ? THEME_STYLES[theme] : null;
  return (
    <div className={styles.headerComponent} data-theme={theme || ''}>
      <div className={styles.headerTitle} style={t ? { color: t.color } : undefined}>
        {t && <span className={styles.headerIcon}>{t.icon}</span>}
        {title}
      </div>
      {subtitle && <div className={styles.headerSubtitle}>{subtitle}</div>}
    </div>
  );
};

const TextComponent: React.FC<{ content: string; style?: string }> = ({ content, style }) => (
  <div className={`${styles.textComponent} ${style === 'muted' ? styles.textMuted : ''}`}>
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
  </div>
);

const ListComponent: React.FC<{ items: string[]; ordered?: boolean }> = ({ items, ordered }) => {
  const ListTag = ordered ? 'ol' : 'ul';
  return (
    <ListTag className={styles.listComponent}>
      {items.map((item, idx) => (
        <li key={idx}>{item}</li>
      ))}
    </ListTag>
  );
};

interface KeyValueItem {
  key: string;
  value: string;
}

const KeyValueComponent: React.FC<{ items: KeyValueItem[] }> = ({ items }) => (
  <div className={styles.keyValueComponent}>
    {items.map((item, idx) => (
      <div key={idx} className={styles.keyValueRow}>
        <span className={styles.keyValueKey}>{item.key}</span>
        <span className={styles.keyValueValue}>{item.value}</span>
      </div>
    ))}
  </div>
);

const TagComponent: React.FC<{ items: string[]; color?: string }> = ({ items, color }) => (
  <div className={styles.tagComponent}>
    {items.map((item, idx) => (
      <Tag key={idx} color={color} className={styles.tagItem}>
        {item}
      </Tag>
    ))}
  </div>
);

const ImageComponent: React.FC<{ src: string; alt?: string }> = ({ src, alt }) => (
  <div className={styles.imageComponent}>
    <Image
      src={src}
      alt={alt || ''}
      className={styles.cardImage}
      preview={{ mask: '预览' }}
    />
  </div>
);

const ButtonComponent: React.FC<{ label: string; url?: string; action?: string; value?: string; param_name?: string; param_value?: string }> = ({ label, url, action, value, param_name, param_value }) => {
  const formCtx = useContext(CardFormContext);
  const sourceId = useContext(CardSourceContext);

  const handleClick = () => {
    if (url) {
      window.open(url, '_blank');
      return;
    }

    // Form mode: set local value instead of sending immediately
    if (action === 'set_value' && formCtx) {
      const key = param_name || (value ? value.split(':')[0].trim() : '');
      const val = param_value || (value ? value.split(':', 1)[1]?.trim() : '');
      if (key) {
        formCtx.setFormValue(key, val || label);
      }
      return;
    }

    // Default: send message immediately
    if (action === 'send_message' && value) {
      dispatchSendMessage(value, sourceId);
    }
  };

  // Determine selected state in form mode
  let isSelected = false;
  if (formCtx && param_name) {
    const currentVal = formCtx.formValues[param_name];
    isSelected = currentVal === (param_value || value || label);
  }

  return (
    <Button
      type={isSelected ? 'primary' : 'default'}
      size="small"
      className={`${styles.buttonComponent} ${isSelected ? styles.buttonSelected : styles.buttonUnselected}`}
      onClick={handleClick}
    >
      {isSelected && <CheckOutlined className={styles.buttonCheckIcon} />}
      {label}
    </Button>
  );
};

const DividerComponent: React.FC = () => <div className={styles.dividerComponent} />;

const DatePickerComponent: React.FC<{ label?: string; param_name: string; action?: string }> = ({ label, param_name, action }) => {
  const formCtx = useContext(CardFormContext);
  const sourceId = useContext(CardSourceContext);
  const [localValue, setLocalValue] = useState<string>('');

  const handleChange = (_date: Dayjs | null, dateString: string) => {
    if (!dateString) return;

    setLocalValue(dateString);

    if (action === 'set_value' && formCtx) {
      formCtx.setFormValue(param_name, dateString);
      return;
    }

    dispatchSendMessage(`${param_name}: ${dateString}`, sourceId);
  };

  return (
    <div className={styles.datePickerComponent}>
      {label && (
        <div className={styles.datePickerLabel}>
          {label}
          {localValue && <span className={styles.fieldValueTag}>{localValue}</span>}
        </div>
      )}
      <DatePicker
        onChange={handleChange}
        format="YYYY-MM-DD"
        placeholder="选择日期"
        className={styles.datePickerInput}
        value={localValue ? dayjs(localValue) : null}
      />
    </div>
  );
};

const SelectComponent: React.FC<{
  label?: string;
  param_name: string;
  options: { label: string; value: string }[];
  action?: string;
}> = ({ label, param_name, options, action }) => {
  const formCtx = useContext(CardFormContext);
  const sourceId = useContext(CardSourceContext);
  const [localValue, setLocalValue] = useState<string | undefined>(undefined);

  const handleChange = (value: string) => {
    setLocalValue(value);

    if (action === 'set_value' && formCtx) {
      formCtx.setFormValue(param_name, value);
      return;
    }

    dispatchSendMessage(`${param_name}: ${value}`, sourceId);
  };

  const selectedLabel = localValue ? options.find(o => o.value === localValue)?.label : undefined;

  return (
    <div className={styles.selectComponent}>
      {label && (
        <div className={styles.selectLabel}>
          {label}
          {selectedLabel && (
            <span className={styles.fieldValueTag}>{selectedLabel}</span>
          )}
        </div>
      )}
      <Select
        options={options}
        placeholder="请选择"
        onChange={handleChange}
        className={styles.selectInput}
        value={localValue}
      />
    </div>
  );
};

const InputComponent: React.FC<{
  label?: string;
  param_name: string;
  placeholder?: string;
  action?: string;
}> = ({ label, param_name, placeholder, action }) => {
  const formCtx = useContext(CardFormContext);
  const sourceId = useContext(CardSourceContext);
  const [value, setValue] = useState('');

  const handleSubmit = () => {
    if (!value.trim()) return;

    if (action === 'set_value' && formCtx) {
      formCtx.setFormValue(param_name, value.trim());
      return;
    }

    dispatchSendMessage(`${param_name}: ${value.trim()}`, sourceId);
    setValue('');
  };

  const savedValue = formCtx?.formValues[param_name];

  return (
    <div className={styles.inputComponent}>
      {label && (
        <div className={styles.inputLabel}>
          {label}
          {savedValue && <span className={styles.fieldValueTag}>{savedValue}</span>}
        </div>
      )}
      <Input.Search
        value={value}
        placeholder={placeholder || '请输入自定义内容'}
        enterButton={action === 'set_value' ? '设置' : '确认'}
        onChange={(e) => setValue(e.target.value)}
        onSearch={handleSubmit}
        className={styles.inputSearch}
      />
    </div>
  );
};

const SubmitButtonComponent: React.FC<{ label?: string }> = ({ label }) => {
  const formCtx = useContext(CardFormContext);
  const sourceId = useContext(CardSourceContext);

  const handleSubmit = () => {
    if (!formCtx) return;
    const entries = Object.entries(formCtx.formValues).filter(([, v]) => v);
    if (entries.length === 0) return;

    const content = entries.map(([k, v]) => `${k}: ${v}`).join('\n');
    dispatchSendMessage(content, sourceId);
  };

  return (
    <Button
      type="primary"
      size="large"
      block
      className={styles.submitButton}
      onClick={handleSubmit}
    >
      {label || '✅ 确认提交'}
    </Button>
  );
};

// Component registry
const componentMap: Record<string, React.FC<any>> = {
  header: HeaderComponent,
  text: TextComponent,
  list: ListComponent,
  key_value: KeyValueComponent,
  image: ImageComponent,
  tag: TagComponent,
  button: ButtonComponent,
  divider: DividerComponent,
  date_picker: DatePickerComponent,
  select: SelectComponent,
  input: InputComponent,
  submit_button: SubmitButtonComponent,
};

function renderComponent(comp: ComponentItem, idx: number): React.ReactNode {
  const C = componentMap[comp.type];
  if (!C) return null;
  return <C key={`${comp.type}-${idx}`} {...comp.props} />;
}


// ------------------------------------------------------------------
// Carousel
// ------------------------------------------------------------------

const Carousel: React.FC<{ slides: SlideData[]; footer?: { components: ComponentItem[] } }> = ({
  slides,
  footer,
}) => {
  const [currentIndex, setCurrentIndex] = useState(0);

  const goTo = useCallback(
    (index: number) => {
      if (index < 0) index = slides.length - 1;
      if (index >= slides.length) index = 0;
      setCurrentIndex(index);
    },
    [slides.length]
  );

  const goPrev = useCallback(() => goTo(currentIndex - 1), [currentIndex, goTo]);
  const goNext = useCallback(() => goTo(currentIndex + 1), [currentIndex, goTo]);

  return (
    <div className={styles.carouselContainer}>
      <div className={styles.carouselViewport}>
        <div
          className={styles.carouselTrack}
          style={{ transform: `translateX(-${currentIndex * 100}%)` }}
        >
          {slides.map((slide, idx) => (
            <div key={idx} className={styles.carouselSlide}>
              <div className={styles.slidePanel}>
                {slide.components.map((comp, cidx) => renderComponent(comp, cidx))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {slides.length > 1 && (
        <>
          <button className={`${styles.carouselArrow} ${styles.carouselArrowLeft}`} onClick={goPrev}>
            <LeftOutlined />
          </button>
          <button className={`${styles.carouselArrow} ${styles.carouselArrowRight}`} onClick={goNext}>
            <RightOutlined />
          </button>
          <div className={styles.carouselDots}>
            {slides.map((_, idx) => (
              <button
                key={idx}
                className={`${styles.carouselDot} ${idx === currentIndex ? styles.carouselDotActive : ''}`}
                onClick={() => goTo(idx)}
              />
            ))}
          </div>
        </>
      )}

      {footer && (
        <div className={styles.cardFooter}>
          {footer.components.map((comp, idx) => renderComponent(comp, idx))}
        </div>
      )}
    </div>
  );
};

// ------------------------------------------------------------------
// Generic Card Renderer
// ------------------------------------------------------------------

const GenericCard: React.FC<{ data: GenericCardData }> = ({ data }) => {
  const { layout = 'stack', theme, slides, footer } = data;
  const isFormMode = (data as any).form_mode === true;

  const [formValues, setFormValues] = useState<Record<string, string>>({});

  const setFormValue = useCallback((key: string, value: string) => {
    setFormValues(prev => ({ ...prev, [key]: value }));
  }, []);

  if (!slides || slides.length === 0) {
    return null;
  }

  const cardContent = (
    <>
      {slides[0]?.components.map((comp, idx) => renderComponent(comp, idx))}
      {isFormMode && (
        <SubmitButtonComponent label="✅ 确认提交" />
      )}
      {footer && footer.components.map((comp, idx) => renderComponent(comp, idx))}
    </>
  );

  // Multiple slides → carousel
  if (layout === 'carousel' && slides.length > 1) {
    return (
      <CardFormContext.Provider value={{ formValues, setFormValue }}>
        <Carousel slides={slides} footer={footer} />
      </CardFormContext.Provider>
    );
  }

  // Single slide / stack layout → vertical stack
  if (isFormMode) {
    return (
      <CardFormContext.Provider value={{ formValues, setFormValue }}>
        <div className={styles.stackContainer} data-theme={theme || ''}>
          {cardContent}
        </div>
      </CardFormContext.Provider>
    );
  }

  return (
    <div className={styles.stackContainer} data-theme={theme || ''}>
      {cardContent}
    </div>
  );
};

// ------------------------------------------------------------------
// Action Card Renderer (backward compatible)
// ------------------------------------------------------------------

const ActionCard: React.FC<{ data: CardData['data'] }> = ({ data }) => {
  const text = data?.appHandleText;
  const actions = data?.appHandleDataResult;

  if (!text || !actions || actions.length === 0) {
    return null;
  }

  return (
    <div className={styles.actionCard}>
      {text && <div className={styles.actionText}>{text}</div>}
      <div className={styles.actionButtons}>
        {actions.map((action, idx) => (
          <Button
            key={idx}
            type="primary"
            size="large"
            block
            className={styles.actionButton}
            onClick={() => {
              if (action.appLink) {
                window.open(action.appLink, '_blank');
              }
            }}
          >
            {action.appIcon && (
              <img src={action.appIcon} alt="" className={styles.actionIcon} />
            )}
            {action.appName || 'Open'}
          </Button>
        ))}
      </div>
    </div>
  );
};

// ------------------------------------------------------------------
// Main CardRenderer
// ------------------------------------------------------------------

const CardRenderer: React.FC<CardRendererProps> = ({ card, sourceId }) => {
  const { card_type, data } = card;

  const content = card_type === 'generic'
    ? <GenericCard data={data as GenericCardData} />
    : <ActionCard data={data} />;

  return (
    <CardSourceContext.Provider value={sourceId}>
      {content}
    </CardSourceContext.Provider>
  );
};

export default CardRenderer;

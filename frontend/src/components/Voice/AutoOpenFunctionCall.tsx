import { useState } from 'react';
import type { FunctionCallData } from '@pipecat-ai/client-react';
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from '@pipecat-ai/voice-ui-kit';
import { ChevronRight, LoaderCircle, Check, X } from 'lucide-react';

export function AutoOpenFunctionCall({ functionCall }: { functionCall: FunctionCallData }) {
  const isCompleted = functionCall.status === 'completed';
  const [manualOpen, setManualOpen] = useState(isCompleted);
  const open = isCompleted || manualOpen;
  const hasDetails =
    (functionCall.args && Object.keys(functionCall.args).length > 0) ||
    functionCall.result !== undefined;

  const statusIcon = () => {
    if (functionCall.status === 'completed' && functionCall.cancelled) {
      return <X size={14} className="text-destructive" />;
    }
    switch (functionCall.status) {
      case 'started':
      case 'in_progress':
        return <LoaderCircle size={14} className="animate-spin" />;
      case 'completed':
        return <Check size={14} className="text-green-600" />;
      default:
        return null;
    }
  };

  if (!hasDetails) {
    return (
      <div className="flex flex-col gap-1">
        <button className="flex items-center gap-2 text-xs font-mono text-muted-foreground transition-colors cursor-default select-none">
          {statusIcon()}
          <span className="font-semibold">Function call</span>
          {functionCall.function_name && (
            <span className="text-muted-foreground">({functionCall.function_name})</span>
          )}
        </button>
      </div>
    );
  }

  return (
    <Collapsible open={open} onOpenChange={setManualOpen}>
      <div className="flex flex-col gap-1">
        <CollapsibleTrigger asChild disabled={!hasDetails}>
          <button className="flex items-center gap-2 text-xs font-mono text-muted-foreground transition-colors hover:text-foreground cursor-pointer select-none">
            <ChevronRight
              size={14}
              className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
            />
            {statusIcon()}
            <span className="font-semibold">Function call</span>
            {functionCall.function_name && (
              <span className="text-muted-foreground">({functionCall.function_name})</span>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="pl-3 border-l-2 border-muted text-xs font-mono flex flex-col gap-2 mt-1 ml-3.5">
            {functionCall.args && Object.keys(functionCall.args).length > 0 && (
              <div>
                <div className="font-semibold text-muted-foreground mb-1">Arguments</div>
                <pre className="bg-muted/50 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
                  {JSON.stringify(functionCall.args, null, 2)}
                </pre>
              </div>
            )}
            {functionCall.result !== undefined && (
              <div>
                <div className="font-semibold text-muted-foreground mb-1">Result</div>
                <pre className="bg-muted/50 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
                  {typeof functionCall.result === 'string'
                    ? functionCall.result
                    : JSON.stringify(functionCall.result, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

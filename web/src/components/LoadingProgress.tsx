import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCircleNotch } from '@fortawesome/free-solid-svg-icons';

export default function LoadingProgress() {
  return (
    <div className="w-full mt-4 flex flex-col items-center gap-2 opacity-100 transition-opacity">
      <div className="flex items-center gap-2 text-[12px] font-medium text-primary">
        <FontAwesomeIcon icon={faCircleNotch} spin />
        <span>Analyzing knowledge base...</span>
      </div>
      <div className="w-full h-1.5 bg-surface rounded-full overflow-hidden">
        <div className="h-full bg-primary w-2/3 rounded-full relative overflow-hidden">
          <div className="absolute inset-0 shimmer" />
        </div>
      </div>
    </div>
  );
}

export default function Loading() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-7 bg-[#EAECF0] rounded-xl w-1/3" />
      <div className="h-4 bg-[#F2F4F7] rounded w-2/3" />
      <div className="grid grid-cols-3 gap-3">
        <div className="h-24 bg-white border rounded-xl" />
        <div className="h-24 bg-white border rounded-xl" />
        <div className="h-24 bg-white border rounded-xl" />
      </div>
      <div className="h-48 bg-white border rounded-xl" />
    </div>
  );
}

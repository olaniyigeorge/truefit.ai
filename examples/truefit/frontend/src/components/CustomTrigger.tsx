import {useSidebar} from "@/components/ui/sidebar";
import {Button} from "@/components/ui/button";
import { Menu} from "lucide-react";


const CustomTrigger = () =>  {

    const {toggleSidebar, state} = useSidebar()

    return(
        <Button
            variant="ghost"
            size="icon"
            onClick={toggleSidebar}
            className="relative z-50 left-2 top-4 h-8! w-8! rounded-md! border border-border bg-secondary! text-foreground! shadow-sm hover:bg-accent! hover:text-accent-foreground! focus-visible:ring-2! focus-visible:ring-primary!"
        >
            <Menu className={state == "collapsed" ? "rotate-180" : ""} />
            <span className="sr-only">toggle sidebar</span>
        </Button>
    )
}

export default CustomTrigger

package duck

import (
	"duckthrift/gen"
)

func reader(d duck) string {
	d := duck.NewDuck()
	return d.GetQuack()
}
